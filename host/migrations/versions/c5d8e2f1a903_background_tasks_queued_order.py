"""Index the default newest-first task listing, with NULL timestamps last. (framework 0.0.44)

Revision ID: c5d8e2f1a903
Revises: e805a1b2c3d4
"""

import sqlalchemy as sa
from alembic import op

revision = "c5d8e2f1a903"
down_revision = "e805a1b2c3d4"
branch_labels = None
depends_on = None

_TABLE = "background_tasks_task_execution"
_INDEX = "ix_background_tasks_task_execution_queued_order"


def upgrade() -> None:
    # Hand-written: SQLite autogenerate cannot reflect expression indexes.
    op.create_index(_INDEX, _TABLE, [sa.text("(queued_at IS NULL)"), sa.text("queued_at DESC")])


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
