"""users: refresh-token families, #625 (framework 0.0.41)

Revision ID: a625f0b7c912
Revises: f733c7938fd1
"""

import sqlalchemy as sa
from alembic import op

revision = "a625f0b7c912"
down_revision = "f733c7938fd1"
branch_labels = ("users",)
depends_on = None

_TABLE = "users_refresh_token"
_INDEX = "ix_users_refresh_token_family_id"


def upgrade() -> None:
    op.add_column(_TABLE, sa.Column("family_id", sa.Uuid(), nullable=True))
    tokens = sa.table(_TABLE, sa.column("token", sa.Uuid()), sa.column("family_id", sa.Uuid()))
    # Historical rotations have no lineage; each existing token starts a family.
    op.execute(tokens.update().values(family_id=tokens.c.token))
    with op.batch_alter_table(_TABLE) as batch:
        batch.alter_column("family_id", existing_type=sa.Uuid(), nullable=False)
        batch.create_index(_INDEX, ["family_id"])


def downgrade() -> None:
    with op.batch_alter_table(_TABLE) as batch:
        batch.drop_index(_INDEX)
        batch.drop_column("family_id")
