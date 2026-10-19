"""tenants: one open invitation per (tenant, email) (framework 0.0.36)

Revision ID: 4ae4d020a2f2
Revises: 6afd6d2551f7
Create Date: 2026-10-19

Concurrent invites to one address each passed the service's duplicate check
and each inserted a row; a partial unique index makes the database the
arbiter. Existing duplicates are collapsed first (newest kept), or the index
would fail. This is the framework's own revision ``f1a9c3d7b2e4``, ported
unchanged into this host's history, since the host owns its migrations.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4ae4d020a2f2"
down_revision: str | None = "6afd6d2551f7"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_INDEX = "uq_tenants_invitation_open_email"


def upgrade() -> None:
    op.execute(
        sa.text(
            "DELETE FROM tenants_invitation WHERE accepted_at IS NULL AND id NOT IN ("
            " SELECT MAX(id) FROM tenants_invitation WHERE accepted_at IS NULL"
            " GROUP BY tenant_id, email)"
        )
    )
    op.create_index(
        _INDEX,
        "tenants_invitation",
        ["tenant_id", "email"],
        unique=True,
        sqlite_where=sa.text("accepted_at IS NULL"),
        postgresql_where=sa.text("accepted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index(_INDEX, table_name="tenants_invitation")
