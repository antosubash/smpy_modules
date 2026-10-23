"""users_refresh_token: timestamps become timestamptz (sqlmodel 0.0.45+)

Revision ID: 9d83e789a5b4
Revises: b65e04cf65d7
Create Date: 2026-10-23

Host-only: the framework ships no revision for this. ``RefreshToken`` declares
``created_at``, ``expires_at`` and ``revoked_at`` as bare ``datetime`` fields,
and SQLModel 0.0.45+ maps a bare ``datetime`` to its tz-aware
``UTCDateTime`` (``DateTime(timezone=True)``). Framework 0.0.37+ imports
``UTCDateTime`` from SQLModel, so the old ``sqlmodel<0.0.45`` hold (#170) is
no longer possible, and on Postgres the columns created as ``timestamp
without time zone`` drift from the model (``alembic check`` fails) and refuse
the aware values ``UTCDateTime`` binds.

The stored values were always UTC (the framework writes ``datetime.now(UTC)``),
so ``AT TIME ZONE 'UTC'`` reinterprets them without shifting an instant.
SQLite has a single ``DATETIME`` affinity for both, so nothing runs there.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "9d83e789a5b4"
down_revision: str | None = "b65e04cf65d7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users_refresh_token"
_COLUMNS = (("created_at", False), ("expires_at", False), ("revoked_at", True))


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name, nullable in _COLUMNS:
        op.alter_column(
            _TABLE,
            name,
            existing_type=sa.DateTime(),
            type_=sa.DateTime(timezone=True),
            existing_nullable=nullable,
            postgresql_using=f"{name} AT TIME ZONE 'UTC'",
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return
    for name, nullable in _COLUMNS:
        op.alter_column(
            _TABLE,
            name,
            existing_type=sa.DateTime(timezone=True),
            type_=sa.DateTime(),
            existing_nullable=nullable,
            postgresql_using=f"{name} AT TIME ZONE 'UTC'",
        )
