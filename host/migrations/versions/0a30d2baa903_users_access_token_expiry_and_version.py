"""users: access-token expires_at and session_version (framework 0.0.35)

Revision ID: 0a30d2baa903
Revises: 69fec7894faf
Create Date: 2026-10-01

The framework's own revision ``b4c1e7d9a025``, ported into this host's
history like ``69fec7894faf`` before it.

``expires_at`` moves the token deadline from one process-wide constant onto
each row; ``session_version`` is the bearer half of "sign out everywhere".
Both are backfilled with the values existing rows were minted under — thirty
days from ``created_at``, and the owning account's current counter — so
upgrading signs nobody out and leaves no NULL for the read path to fail open
on. ``expires_at`` is added nullable, backfilled, then made ``NOT NULL``.

Typed ``TIMESTAMPAware`` like ``created_at`` beside it (``ed06f4584f6b``), not
the framework revision's ``DateTime``: the two are the same column on
Postgres, but on SQLite ``DateTime`` reflects as ``DATETIME`` and ``alembic
check`` reports a type change against the model.
"""

from collections.abc import Sequence

import fastapi_users_db_sqlalchemy.generics
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "0a30d2baa903"
down_revision: str | None = "69fec7894faf"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users_access_token",
        sa.Column(
            "expires_at",
            fastapi_users_db_sqlalchemy.generics.TIMESTAMPAware(timezone=True),
            nullable=True,
        ),
    )
    op.add_column(
        "users_access_token",
        sa.Column("session_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )

    if op.get_bind().dialect.name == "postgresql":
        deadline = "created_at + INTERVAL '30 days'"
    else:
        deadline = "datetime(created_at, '+30 days')"
    op.execute(f"UPDATE users_access_token SET expires_at = {deadline}")
    op.execute(
        "UPDATE users_access_token SET session_version = COALESCE("
        "(SELECT session_version FROM users_user WHERE users_user.id = users_access_token.user_id)"
        ", 0)"
    )

    with op.batch_alter_table("users_access_token") as batch:
        batch.alter_column(
            "expires_at",
            existing_type=fastapi_users_db_sqlalchemy.generics.TIMESTAMPAware(timezone=True),
            nullable=False,
        )
    op.create_index(
        "ix_users_access_token_expires_at", "users_access_token", ["expires_at"], unique=False
    )


def downgrade() -> None:
    op.drop_index("ix_users_access_token_expires_at", table_name="users_access_token")
    op.drop_column("users_access_token", "session_version")
    op.drop_column("users_access_token", "expires_at")
