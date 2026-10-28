"""background_tasks: the task_execution table (framework 0.0.41)

Revision ID: c9e3a5f1b7d2
Revises: 714e9f08e819
Create Date: 2026-10-28

The framework creates ``background_tasks_task_execution`` in its initial schema
(``77162e7b184b``) and has no revision chain of its own for it. This host never
depended on ``background_tasks`` before 0.0.41, so the table is missing here and
the ported revisions that follow (``b5d3f08a6e17``, ``bb906e1a1089``) alter it.
It is that initial table, ported as the framework left it at the time, except
that the four ``*_at`` columns are created ``timestamptz`` straight away: the
framework retypes them later in ``e5f2a8c1d7b3``, which has nothing to do on a
table created timezone-aware.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c9e3a5f1b7d2"
down_revision: str | None = "714e9f08e819"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "background_tasks_task_execution"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", sa.String(length=255), nullable=True),
        sa.Column("updated_by", sa.String(length=255), nullable=True),
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("celery_task_id", sa.String(length=64), nullable=True),
        sa.Column("task_name", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("queue", sa.String(length=64), nullable=False),
        sa.Column("args", sa.JSON(), nullable=True),
        sa.Column("kwargs", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("traceback", sa.String(), nullable=True),
        sa.Column("exception_type", sa.String(length=255), nullable=True),
        sa.Column("worker", sa.String(length=255), nullable=True),
        sa.Column("retries", sa.Integer(), nullable=False),
        sa.Column("retried_from_id", sa.Uuid(), nullable=True),
        sa.Column("queued_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["retried_from_id"],
            [f"{_TABLE}.id"],
            name=op.f(
                "fk_background_tasks_task_execution_retried_from_id_background_tasks_task_execution"
            ),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_tasks_task_execution")),
    )
    op.create_index(
        op.f("ix_background_tasks_task_execution_celery_task_id"),
        _TABLE,
        ["celery_task_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_background_tasks_task_execution_retried_from_id"),
        _TABLE,
        ["retried_from_id"],
        unique=False,
    )
    op.create_index(
        op.f("ix_background_tasks_task_execution_status"), _TABLE, ["status"], unique=False
    )
    op.create_index(
        "ix_background_tasks_task_execution_status_queued",
        _TABLE,
        ["status", "queued_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_background_tasks_task_execution_task_name"), _TABLE, ["task_name"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_background_tasks_task_execution_task_name"), table_name=_TABLE)
    op.drop_index("ix_background_tasks_task_execution_status_queued", table_name=_TABLE)
    op.drop_index(op.f("ix_background_tasks_task_execution_status"), table_name=_TABLE)
    op.drop_index(op.f("ix_background_tasks_task_execution_retried_from_id"), table_name=_TABLE)
    op.drop_index(op.f("ix_background_tasks_task_execution_celery_task_id"), table_name=_TABLE)
    op.drop_table(_TABLE)
