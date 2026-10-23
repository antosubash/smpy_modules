"""users: login lockout columns (framework 0.0.38)

Revision ID: 12ebd9541f76
Revises: 42b922de3574
Create Date: 2026-10-23

The framework's own revision ``c8e4f1a2b6d9`` (#530), ported unchanged into
this host's history, since the host owns its migrations.

Login lockout moves from per-worker memory to the user row, so it holds
across workers, source IPs and restarts. Every existing account starts
unlocked with a zero count; nothing to backfill.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "12ebd9541f76"
down_revision: str | None = "42b922de3574"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users_user",
        sa.Column(
            "failed_login_count",
            sa.Integer(),
            server_default=sa.text("0"),
            nullable=False,
        ),
    )
    op.add_column(
        "users_user",
        sa.Column("last_failed_login_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users_user",
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users_user", "locked_until")
    op.drop_column("users_user", "last_failed_login_at")
    op.drop_column("users_user", "failed_login_count")
