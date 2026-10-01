"""users: refresh-token user_id Uuid -> GUID (framework 0.0.35)

Revision ID: 25633593dd54
Revises: 0a30d2baa903
Create Date: 2026-10-01

The framework's own revision ``c3a1d7e45f20``, ported into this host's
history like ``69fec7894faf`` and ``0a30d2baa903`` before it.

``User.id`` uses fastapi-users' ``GUID``; ``RefreshToken.user_id`` was left on
SQLModel's default ``Uuid`` until 0.0.35. The two are identical on Postgres
(both ``UUID``), so this is a no-op there. On SQLite ``Uuid`` stores the bare
32-char hex and ``GUID`` the 36-char dashed form, so the foreign key never
matched a parent row — silently, while SQLite ran with foreign keys off
(framework #339; 0.0.35 turns them on). The rewrite dashes the stored values,
drops tokens whose user is gone (they could not authenticate, and would block
the FK-checked rebuild), and retypes the column.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy.generics import GUID

# revision identifiers, used by Alembic.
revision: str = "25633593dd54"
down_revision: str | None = "0a30d2baa903"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "users_refresh_token"

# 32-char hex -> 8-4-4-4-12 dashed form, in SQLite's string functions.
_TO_DASHED = (
    "substr(user_id, 1, 8) || '-' || substr(user_id, 9, 4) || '-' || "
    "substr(user_id, 13, 4) || '-' || substr(user_id, 17, 4) || '-' || substr(user_id, 21, 12)"
)
_TO_HEX = "replace(user_id, '-', '')"


def _rewrite(expression: str, where: str) -> None:
    op.execute(f"UPDATE {_TABLE} SET user_id = {expression} WHERE {where}")


def upgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    _rewrite(_TO_DASHED, "length(user_id) = 32")
    op.execute(f"DELETE FROM {_TABLE} WHERE user_id NOT IN (SELECT id FROM users_user)")
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.alter_column("user_id", type_=GUID(), existing_type=sa.Uuid(), nullable=False)


def downgrade() -> None:
    if op.get_bind().dialect.name != "sqlite":
        return
    with op.batch_alter_table(_TABLE) as batch_op:
        batch_op.alter_column("user_id", type_=sa.Uuid(), existing_type=GUID(), nullable=False)
    _rewrite(_TO_HEX, "length(user_id) = 36")
