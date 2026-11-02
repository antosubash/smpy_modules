"""background_tasks_task_execution: add nullable tenant_id (framework 0.0.41)

NULL means a beat / platform publish (no tenant bound), which is also what
every pre-existing row is. The table is deliberately not ``MultiTenantMixin``:
those rows have no tenant and strict mode would raise on their insert. See
GH #371.

background_tasks has no migration chain of its own (its tables came in with
the host's initial schema), so this extends the mainline head.

Revision ID: b5d3f08a6e17
Revises: c9e3a5f1b7d2
Create Date: 2026-10-01 13:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5d3f08a6e17"
down_revision: str | None = "c9e3a5f1b7d2"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "background_tasks_task_execution"
_SINGLE = "ix_background_tasks_task_execution_tenant_id"
_COMPOSITE = "ix_background_tasks_task_execution_tenant_status_queued"


def upgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.add_column(sa.Column("tenant_id", sa.String(length=50), nullable=True))
        batch.create_index(_SINGLE, ["tenant_id"], unique=False)
        batch.create_index(_COMPOSITE, ["tenant_id", "status", "queued_at"], unique=False)


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index(_COMPOSITE)
        batch.drop_index(_SINGLE)
        batch.drop_column("tenant_id")
