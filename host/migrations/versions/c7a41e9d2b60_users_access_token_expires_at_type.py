"""users_access_token.expires_at: declared type matches the model (framework 0.0.45)

Revision ID: c7a41e9d2b60
Revises: e480d7dd348f
Create Date: 2026-11-17

Host-only: the framework ships no revision for this. ``0a30d2baa903`` added
``expires_at`` typed ``TIMESTAMPAware``, which SQLite reflects as ``TIMESTAMP``.
Framework 0.0.45 declares the column ``AwareDateTime`` (rendered as
``DateTime(timezone=True)``), so ``alembic check`` on SQLite reports a type
change on a database that ran ``0a30d2baa903``. That revision is shipped and
stays as it was; this one converges old and new databases instead.

SQLite only: the batch alter rebuilds the table with the declared type (same
``DATETIME`` affinity, values untouched). Postgres already has ``TIMESTAMP WITH
TIME ZONE``, so nothing runs there.
"""

from collections.abc import Sequence

import fastapi_users_db_sqlalchemy.generics
import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7a41e9d2b60"
down_revision: str | None = "e480d7dd348f"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users_access_token"


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column(
            "expires_at",
            existing_type=fastapi_users_db_sqlalchemy.generics.TIMESTAMPAware(timezone=True),
            type_=sa.DateTime(timezone=True),
            existing_nullable=False,
        )


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column(
            "expires_at",
            existing_type=sa.DateTime(timezone=True),
            type_=fastapi_users_db_sqlalchemy.generics.TIMESTAMPAware(timezone=True),
            existing_nullable=False,
        )
