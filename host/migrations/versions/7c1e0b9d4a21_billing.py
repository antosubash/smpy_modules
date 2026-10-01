"""billing: plans, customers, subscriptions, webhook events

Revision ID: 7c1e0b9d4a21
Revises: 25633593dd54
Create Date: 2026-10-01 16:37:56.541596
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '7c1e0b9d4a21'
down_revision: str | None = '25633593dd54'
branch_labels: str | Sequence[str] | None = ("billing",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('billing_customer',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.Column('updated_by', sa.String(length=255), nullable=True),
    sa.Column('tenant_id', sa.String(length=32), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('provider_customer_id', sa.String(length=255), nullable=True),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.Column('checkout_session_id', sa.String(length=255), nullable=True),
    sa.PrimaryKeyConstraint('tenant_id', name=op.f('pk_billing_customer'))
    )
    op.create_index(op.f('ix_billing_customer_provider_customer_id'), 'billing_customer', ['provider_customer_id'], unique=True)
    op.create_table('billing_plan',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.Column('updated_by', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('key', sa.String(length=64), nullable=False),
    sa.Column('name', sa.String(length=120), nullable=False),
    sa.Column('description', sa.String(length=500), nullable=False),
    sa.Column('pricing_model', sa.String(length=20), nullable=False),
    sa.Column('currency', sa.String(length=3), nullable=False),
    sa.Column('amount_month', sa.Integer(), nullable=True),
    sa.Column('amount_year', sa.Integer(), nullable=True),
    sa.Column('stripe_price_month', sa.String(length=255), nullable=True),
    sa.Column('stripe_price_year', sa.String(length=255), nullable=True),
    sa.Column('trial_days', sa.Integer(), nullable=False),
    sa.Column('limits', sa.JSON(), nullable=False),
    sa.Column('features', sa.JSON(), nullable=False),
    sa.Column('is_default', sa.Boolean(), nullable=False),
    sa.Column('is_public', sa.Boolean(), nullable=False),
    sa.Column('sort_order', sa.Integer(), nullable=False),
    sa.Column('archived_at', sa.DateTime(timezone=True), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_plan')),
    sa.UniqueConstraint('stripe_price_month'),
    sa.UniqueConstraint('stripe_price_year')
    )
    op.create_index(op.f('ix_billing_plan_key'), 'billing_plan', ['key'], unique=True)
    op.create_table('billing_webhook_event',
    sa.Column('id', sa.String(length=255), nullable=False),
    sa.Column('provider', sa.String(length=20), nullable=False),
    sa.Column('type', sa.String(length=100), nullable=False),
    sa.Column('received_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('processed_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('error', sa.Text(), nullable=True),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_webhook_event'))
    )
    op.create_table('billing_subscription',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.Column('updated_by', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.String(length=32), nullable=False),
    sa.Column('plan_id', sa.Integer(), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.Column('interval', sa.String(length=10), nullable=True),
    sa.Column('provider_subscription_id', sa.String(length=255), nullable=True),
    sa.Column('quantity', sa.Integer(), nullable=False),
    sa.Column('trial_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('current_period_end', sa.DateTime(timezone=True), nullable=True),
    sa.Column('cancel_at_period_end', sa.Boolean(), nullable=False),
    sa.Column('suspended_by_billing', sa.Boolean(), nullable=False),
    sa.Column('synced_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['plan_id'], ['billing_plan.id'], name=op.f('fk_billing_subscription_plan_id_billing_plan')),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_billing_subscription'))
    )
    op.create_index(op.f('ix_billing_subscription_provider_subscription_id'), 'billing_subscription', ['provider_subscription_id'], unique=True)
    op.create_index(op.f('ix_billing_subscription_status'), 'billing_subscription', ['status'], unique=False)
    op.create_index(op.f('ix_billing_subscription_tenant_id'), 'billing_subscription', ['tenant_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_billing_subscription_tenant_id'), table_name='billing_subscription')
    op.drop_index(op.f('ix_billing_subscription_status'), table_name='billing_subscription')
    op.drop_index(op.f('ix_billing_subscription_provider_subscription_id'), table_name='billing_subscription')
    op.drop_table('billing_subscription')
    op.drop_table('billing_webhook_event')
    op.drop_index(op.f('ix_billing_plan_key'), table_name='billing_plan')
    op.drop_table('billing_plan')
    op.drop_index(op.f('ix_billing_customer_provider_customer_id'), table_name='billing_customer')
    op.drop_table('billing_customer')
    # ### end Alembic commands ###
