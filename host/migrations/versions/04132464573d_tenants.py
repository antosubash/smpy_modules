"""tenants: organisations, memberships, invitations (framework 0.0.35)

Revision ID: 04132464573d
Revises: 25633593dd54
Create Date: 2026-10-01 16:37:56.541596
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = '04132464573d'
down_revision: str | None = '25633593dd54'
branch_labels: str | Sequence[str] | None = ("tenants",)
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table('tenants_tenant',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.Column('updated_by', sa.String(length=255), nullable=True),
    sa.Column('id', sa.String(length=32), nullable=False),
    sa.Column('slug', sa.String(length=50), nullable=False),
    sa.Column('name', sa.String(length=200), nullable=False),
    sa.Column('status', sa.String(length=20), nullable=False),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenants_tenant'))
    )
    op.create_index(op.f('ix_tenants_tenant_slug'), 'tenants_tenant', ['slug'], unique=True)
    op.create_index(op.f('ix_tenants_tenant_status'), 'tenants_tenant', ['status'], unique=False)
    op.create_table('tenants_invitation',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.Column('updated_by', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.String(length=32), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('token_hash', sa.String(length=64), nullable=False),
    sa.Column('expires_at', sa.DateTime(timezone=True), nullable=False),
    sa.Column('accepted_at', sa.DateTime(timezone=True), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants_tenant.id'], name=op.f('fk_tenants_invitation_tenant_id_tenants_tenant'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenants_invitation'))
    )
    op.create_index(op.f('ix_tenants_invitation_tenant_id'), 'tenants_invitation', ['tenant_id'], unique=False)
    op.create_index(op.f('ix_tenants_invitation_token_hash'), 'tenants_invitation', ['token_hash'], unique=True)
    op.create_table('tenants_membership',
    sa.Column('created_at', sa.DateTime(timezone=True), server_default=sa.text('(CURRENT_TIMESTAMP)'), nullable=False),
    sa.Column('updated_at', sa.DateTime(timezone=True), nullable=True),
    sa.Column('created_by', sa.String(length=255), nullable=True),
    sa.Column('updated_by', sa.String(length=255), nullable=True),
    sa.Column('id', sa.Integer(), nullable=False),
    sa.Column('tenant_id', sa.String(length=32), nullable=False),
    sa.Column('user_id', sa.String(length=64), nullable=False),
    sa.Column('role', sa.String(length=20), nullable=False),
    sa.Column('email', sa.String(length=320), nullable=True),
    sa.ForeignKeyConstraint(['tenant_id'], ['tenants_tenant.id'], name=op.f('fk_tenants_membership_tenant_id_tenants_tenant'), ondelete='CASCADE'),
    sa.PrimaryKeyConstraint('id', name=op.f('pk_tenants_membership')),
    sa.UniqueConstraint('tenant_id', 'user_id', name='uq_tenants_membership_tenant_user')
    )
    op.create_index('ix_tenants_membership_user', 'tenants_membership', ['user_id'], unique=False)
    # ### end Alembic commands ###


def downgrade() -> None:
    op.drop_index('ix_tenants_membership_user', table_name='tenants_membership')
    op.drop_table('tenants_membership')
    op.drop_index(op.f('ix_tenants_invitation_token_hash'), table_name='tenants_invitation')
    op.drop_index(op.f('ix_tenants_invitation_tenant_id'), table_name='tenants_invitation')
    op.drop_table('tenants_invitation')
    op.drop_index(op.f('ix_tenants_tenant_status'), table_name='tenants_tenant')
    op.drop_index(op.f('ix_tenants_tenant_slug'), table_name='tenants_tenant')
    op.drop_table('tenants_tenant')
