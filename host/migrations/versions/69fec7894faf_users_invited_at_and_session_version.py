"""users: invited_at and session_version (framework 0.0.35)

Revision ID: 69fec7894faf
Revises: 4ecb931245dd
Create Date: 2026-10-01

The framework's ``users`` models gained these columns between 0.0.26 and
0.0.35; ``alembic check`` on Postgres reported them as drift once the host
moved to 0.0.35. This is the framework's own revision ``f53464f5ac43``, ported
unchanged into this host's history, since the host owns its migrations.

``invited_at`` separates an admin-created invitation from a self-signup. Left
NULL for every existing account: backfilling it from ``created_at`` would
invent invitations nobody sent. ``session_version`` backs "sign out
everywhere"; it defaults to 0 in the column and in any session that predates
it, so upgrading signs nobody out.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "69fec7894faf"
down_revision: str | None = "4ecb931245dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "users_user",
        sa.Column("invited_at", sa.DateTime(timezone=True), nullable=True),
    )
    op.add_column(
        "users_user",
        sa.Column("session_version", sa.Integer(), server_default=sa.text("0"), nullable=False),
    )


def downgrade() -> None:
    # Plain drops, not ``batch_alter_table``: on SQLite a batch rebuild
    # recreates the table from reflection, which cannot see the expression
    # index ``ix_users_user_email_lower`` (``d2b7a1c4e905``) and drops it.
    op.drop_column("users_user", "session_version")
    op.drop_column("users_user", "invited_at")
