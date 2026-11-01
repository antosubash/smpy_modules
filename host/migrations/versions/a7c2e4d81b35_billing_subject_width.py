"""billing subject width

A billing subject is a tenant id (32 characters), ``"default"`` or, in user
mode, ``"user:<uuid>"`` (41). Widens the six ``tenant_id`` columns of
sm_billing to 64 (#274).

Revision ID: a7c2e4d81b35
Revises: f5b1c3e8a207
Create Date: 2026-11-01 12:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "a7c2e4d81b35"
down_revision: str | None = "f5b1c3e8a207"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = (
    "billing_customer",
    "billing_subscription",
    "billing_usage_event",
    "billing_usage_period",
    "billing_usage_gauge",
    "billing_usage_hold",
)


def _resize(old: int, new: int) -> None:
    for table in _TABLES:
        with op.batch_alter_table(table) as batch:
            batch.alter_column(
                "tenant_id",
                existing_type=sa.String(old),
                type_=sa.String(new),
                existing_nullable=False,
            )


def upgrade() -> None:
    _resize(32, 64)


def downgrade() -> None:
    _resize(64, 32)
