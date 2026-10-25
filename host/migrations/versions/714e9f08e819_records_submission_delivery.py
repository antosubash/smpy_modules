"""records: who a website submission's notification has reached (#101)

Revision ID: 714e9f08e819
Revises: b1f345f67586
Create Date: 2026-10-25 17:38:56.425483

``records_submission_delivery`` holds one row per (tenant, record, delivery
attempt, recipient), unique, so claiming a recipient before mailing it is the
database's decision: a retry never re-mails a recipient whose send was
recorded, and two outbox workers cannot both send. New and empty.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '714e9f08e819'
down_revision: str | None = 'b1f345f67586'
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('records_submission_delivery',
    sa.Column('tenant_id', sa.String(length=50), nullable=False),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('record_uuid', sa.String(length=32), nullable=False),
    sa.Column('attempt', sa.String(length=64), nullable=False),
    sa.Column('recipient', sa.String(length=320), nullable=False),
    sa.Column('claimed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('claim_token', sa.String(length=32), nullable=True),
    sa.Column('sent_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_records_submission_delivery')),
    sa.UniqueConstraint('tenant_id', 'record_uuid', 'attempt', 'recipient', name='uq_records_submission_delivery_claim')
    )
    op.create_index(op.f('ix_records_submission_delivery_tenant_id'), 'records_submission_delivery', ['tenant_id'], unique=False)


def downgrade() -> None:
    op.drop_index(op.f('ix_records_submission_delivery_tenant_id'), table_name='records_submission_delivery')
    op.drop_table('records_submission_delivery')
