"""Track retired local browser sessions. (framework 0.0.44)

Revision ID: e805a1b2c3d4
Revises: e731a1b2c3d4
"""

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy.generics import GUID
from simple_module_db.types import AwareDateTime

revision = "e805a1b2c3d4"
down_revision = "e731a1b2c3d4"
branch_labels = None
depends_on = None

_TABLE = "users_revoked_session"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("session_id", sa.String(64), primary_key=True, nullable=False),
        sa.Column(
            "user_id", GUID(), sa.ForeignKey("users_user.id", ondelete="CASCADE"), nullable=False
        ),
        sa.Column("expires_at", AwareDateTime(), nullable=False),
    )
    op.create_index("ix_users_revoked_session_user_id", _TABLE, ["user_id"])
    op.create_index("ix_users_revoked_session_expires_at", _TABLE, ["expires_at"])


def downgrade() -> None:
    op.drop_table(_TABLE)
