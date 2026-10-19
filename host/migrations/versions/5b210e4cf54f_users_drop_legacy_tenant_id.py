"""users: drop the legacy tenant_id column (framework 0.0.36)

Revision ID: 5b210e4cf54f
Revises: 04132464573d
Create Date: 2026-10-19

Tenant membership lives in ``tenants_membership`` and the active tenant is
resolved per request, so 0.0.36 removed the copy on the user row (framework
#381). This is the framework's own revision ``d4e8a1b6c392``, ported into this
host's history, with one change: plain drops instead of ``batch_alter_table``.
On SQLite a batch rebuild recreates the table from reflection, which cannot
see the expression index ``ix_users_user_email_lower`` and drops it.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5b210e4cf54f"
down_revision: str | None = "04132464573d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "ix_users_user_tenant_id"


def upgrade() -> None:
    # SQLite drops a column in place once nothing indexes it.
    op.drop_index(_INDEX, table_name="users_user")
    op.drop_column("users_user", "tenant_id")


def downgrade() -> None:
    op.add_column("users_user", sa.Column("tenant_id", sa.String(length=50), nullable=True))
    op.create_index(_INDEX, "users_user", ["tenant_id"], unique=False)
