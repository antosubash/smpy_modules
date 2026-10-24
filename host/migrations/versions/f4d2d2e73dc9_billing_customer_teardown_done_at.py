"""billing customer teardown_done_at

The deleted-tenant teardown's bookkeeping on ``billing_customer`` (#92,
sm_billing.teardown / sm_billing.sweep): ``teardown_done_at`` is stamped once a
deleted tenant's provider subscriptions are canceled, so the reconcile sweep
skips it; ``teardown_attempts`` and ``teardown_next_attempt_at`` back a
teardown that keeps failing off.

Revision ID: f4d2d2e73dc9
Revises: 9d83e789a5b4
Create Date: 2026-10-24 11:20:16.480664
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "f4d2d2e73dc9"
down_revision: str | None = "9d83e789a5b4"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "billing_customer", sa.Column("teardown_done_at", sa.DateTime(timezone=True), nullable=True)
    )
    # Existing rows have never failed a teardown.
    op.add_column(
        "billing_customer",
        sa.Column("teardown_attempts", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "billing_customer",
        sa.Column("teardown_next_attempt_at", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("billing_customer", "teardown_next_attempt_at")
    op.drop_column("billing_customer", "teardown_attempts")
    op.drop_column("billing_customer", "teardown_done_at")
