"""background_tasks_outbox: durable event delivery, GH #459 (framework 0.0.41)

One row per (event, durable handler), written in the publisher's transaction
and delivered by the ``dispatch_outbox`` / ``sweep_outbox`` tasks. ``tenant_id``
is a plain nullable column, as on ``background_tasks_task_execution``: platform
publishes carry no tenant, and the dispatcher reads across tenants. ``scope``
(tenant / platform / unscoped) tells a platform publish from one made with no
tenant bound, which both leave ``tenant_id`` NULL.

background_tasks has no migration chain of its own, so this extends the
mainline head, like ``b5d3f08a6e17``.

Revision ID: e878882924e7
Revises: b5d3f08a6e17
Create Date: 2026-10-15 10:25:29.001223
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e878882924e7"
down_revision: str | None = "b5d3f08a6e17"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLE = "background_tasks_outbox"


def upgrade() -> None:
    op.create_table(
        _TABLE,
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("event_key", sa.String(length=255), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("handler_name", sa.String(length=255), nullable=False),
        sa.Column("tenant_id", sa.String(length=50), nullable=True),
        sa.Column("scope", sa.String(length=20), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("claim_seq", sa.Integer(), nullable=False),
        sa.Column("next_attempt_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("locked_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_background_tasks_outbox")),
    )
    op.create_index(
        "ix_background_tasks_outbox_status_delivered",
        _TABLE,
        ["status", "delivered_at"],
        unique=False,
    )
    op.create_index(
        "ix_background_tasks_outbox_status_locked", _TABLE, ["status", "locked_until"], unique=False
    )
    op.create_index(
        "ix_background_tasks_outbox_status_next_attempt",
        _TABLE,
        ["status", "next_attempt_at"],
        unique=False,
    )
    op.create_index(
        op.f("ix_background_tasks_outbox_tenant_id"), _TABLE, ["tenant_id"], unique=False
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_background_tasks_outbox_tenant_id"), table_name=_TABLE)
    op.drop_index("ix_background_tasks_outbox_status_next_attempt", table_name=_TABLE)
    op.drop_index("ix_background_tasks_outbox_status_locked", table_name=_TABLE)
    op.drop_index("ix_background_tasks_outbox_status_delivered", table_name=_TABLE)
    op.drop_table(_TABLE)
