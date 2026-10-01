"""users: create the ``lower(email)`` index the model has always declared

Revision ID: d2b7a1c4e905
Revises: b81c5f3a27d6
Create Date: 2026-09-21

``users.models.user`` declares
``Index("ix_users_user_email_lower", text("lower(email)"))`` in its
``__table_args__``, but no revision in this host's history ever created it —
so every deployed database has been missing it since ``ed06f4584f6b``.

**It went unnoticed because the drift is invisible on SQLite.** SQLAlchemy
cannot reflect expression-based indexes on that dialect, so ``alembic check``
skips the comparison with a warning and reports "No new upgrade operations
detected". On Postgres the same command reflects the index list properly, finds
nothing matching, and fails with ``add_index('ix_users_user_email_lower')`` —
which is how this was found, while verifying the ``records`` module on
Postgres 16.

The index is created on both dialects: SQLite supports expression indexes even
though it cannot reflect them, and creating it there keeps the two schemas the
same shape rather than encoding the reflection gap into the migration history.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d2b7a1c4e905"
down_revision: str | None = "b81c5f3a27d6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_index(
        "ix_users_user_email_lower",
        "users_user",
        [sa.text("lower(email)")],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_users_user_email_lower", table_name="users_user")
