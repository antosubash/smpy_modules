"""background_tasks: retained log records, GH #537 (framework 0.0.41)

Adds ``background_tasks_log_record``, the table the opt-in log sink writes to.
Indexed for the three reads that exist: one task's lines in time order, a
time-range purge, and a minimum-level search.

Revision ID: 1f5985daa10b
Revises: bb906e1a1089
Create Date: 2026-10-21 18:23:28.568913
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "1f5985daa10b"
down_revision: str | None = "bb906e1a1089"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "background_tasks_log_record"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("level", sa.Integer(), nullable=False),
        sa.Column("logger", sa.String(length=255), nullable=False),
        sa.Column("message", sa.String(length=4096), nullable=False),
        sa.Column("task_id", sa.String(length=64), nullable=True),
        sa.Column("job_id", sa.String(length=64), nullable=True),
        sa.Column("tenant_id", sa.String(length=50), nullable=True),
        sa.Column("correlation_id", sa.String(length=64), nullable=True),
        sa.Column("extra", sa.JSON(), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_tasks_log_record")),
    )
    op.create_index("ix_background_tasks_log_record_task_ts", _TABLE, ["task_id", "ts"])
    op.create_index("ix_background_tasks_log_record_ts", _TABLE, ["ts"])
    op.create_index("ix_background_tasks_log_record_level_ts", _TABLE, ["level", "ts"])


def downgrade() -> None:
    op.drop_index("ix_background_tasks_log_record_level_ts", table_name=_TABLE)
    op.drop_index("ix_background_tasks_log_record_ts", table_name=_TABLE)
    op.drop_index("ix_background_tasks_log_record_task_ts", table_name=_TABLE)
    op.drop_table(_TABLE)
