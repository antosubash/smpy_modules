"""users: store the IdP profile on the OAuth link (#877)

Revision ID: e480d7dd348f
Revises: 541bfbe29a28
Create Date: 2026-11-11 20:53:38.720371
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from simple_module_db.types import AwareDateTime

# revision identifiers, used by Alembic.
revision: str = "e480d7dd348f"
down_revision: str | None = "541bfbe29a28"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users_oauth_account", sa.Column("subject", sa.String(length=320), nullable=True))
    op.add_column(
        "users_oauth_account", sa.Column("username", sa.String(length=320), nullable=True)
    )
    op.add_column(
        "users_oauth_account", sa.Column("display_name", sa.String(length=320), nullable=True)
    )
    op.add_column("users_oauth_account", sa.Column("extra", sa.JSON(), nullable=True))
    op.add_column(
        "users_oauth_account",
        sa.Column("last_sign_in_at", AwareDateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users_oauth_account", "last_sign_in_at")
    op.drop_column("users_oauth_account", "extra")
    op.drop_column("users_oauth_account", "display_name")
    op.drop_column("users_oauth_account", "username")
    op.drop_column("users_oauth_account", "subject")
