"""Index tenant file browsing in page order. (framework 0.0.44)

Revision ID: f6c2d4e8b109
Revises: c5d8e2f1a903
"""

import sqlalchemy as sa
from alembic import op

revision = "f6c2d4e8b109"
down_revision = "c5d8e2f1a903"
branch_labels = None
depends_on = None

_TABLE = "file_storage_stored_file"
_INDEX = "ix_file_storage_stored_file_tenant_browse"


def upgrade() -> None:
    op.create_index(_INDEX, _TABLE, ["tenant_id", "is_deleted", sa.text("created_at DESC"), "id"])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
