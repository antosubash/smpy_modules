"""Shared sealed browser refresh outcomes (#738). (framework 0.0.43)

Revision ID: a738c2e4f601
Revises: c4e9b2a7d613
"""

import sqlalchemy as sa
from alembic import op

revision = "a738c2e4f601"
down_revision = "c4e9b2a7d613"
branch_labels = ("auth",)
depends_on = None


def upgrade() -> None:
    op.create_table(
        "auth_refresh_outcome",
        sa.Column("outcome_key", sa.String(length=128), nullable=False),
        sa.Column("lock_key", sa.String(length=128), nullable=False),
        sa.Column("expires_at", sa.BigInteger(), nullable=False),
        sa.Column("session", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("outcome_key", name=op.f("pk_auth_refresh_outcome")),
    )
    op.create_index("ix_auth_refresh_outcome_expires_at", "auth_refresh_outcome", ["expires_at"])
    op.create_index("ix_auth_refresh_outcome_lock_key", "auth_refresh_outcome", ["lock_key"])


def downgrade() -> None:
    op.drop_index("ix_auth_refresh_outcome_lock_key", table_name="auth_refresh_outcome")
    op.drop_index("ix_auth_refresh_outcome_expires_at", table_name="auth_refresh_outcome")
    op.drop_table("auth_refresh_outcome")
