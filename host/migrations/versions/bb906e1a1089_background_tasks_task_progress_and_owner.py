"""background_tasks: task progress and owner, GH #536 (framework 0.0.41)

``progress_*`` hold the latest report a task body sends through
``heartbeat(progress=...)``; ``owner_user_id`` is the user whose request
enqueued the task, so that user can read its status without a task-admin
permission. All columns are nullable plain values: beat and platform
publishes have no owner and most tasks never report progress. The owner is
indexed (the status endpoint filters on it); the others are not.

Starts the ``background_tasks`` label; it extends the mainline head like
``b5d3f08a6e17`` and ``e878882924e7`` did.

Revision ID: bb906e1a1089
Revises: e878882924e7
Create Date: 2026-10-21 18:09:59.606581
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "bb906e1a1089"
down_revision: str | None = "e878882924e7"
branch_labels: str | Sequence[str] | None = ("background_tasks",)
depends_on: str | Sequence[str] | None = None

_TABLE = "background_tasks_task_execution"
_OWNER_INDEX = "ix_background_tasks_task_execution_owner_user_id"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("owner_user_id", sa.String(length=64), nullable=True))
    op.add_column(_TABLE, sa.Column("progress_current", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("progress_total", sa.Integer(), nullable=True))
    op.add_column(_TABLE, sa.Column("progress_message", sa.String(length=255), nullable=True))
    op.add_column(_TABLE, sa.Column("progress_phase", sa.String(length=64), nullable=True))
    op.create_index(_OWNER_INDEX, _TABLE, ["owner_user_id"], unique=False)


def downgrade() -> None:
    op.drop_index(_OWNER_INDEX, table_name=_TABLE)
    op.drop_column(_TABLE, "progress_phase")
    op.drop_column(_TABLE, "progress_message")
    op.drop_column(_TABLE, "progress_total")
    op.drop_column(_TABLE, "progress_current")
    op.drop_column(_TABLE, "owner_user_id")
