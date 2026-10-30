"""users: hash bearer tokens at rest, #626 (framework 0.0.41)

Revision ID: a626b1c8d023
Revises: a625f0b7c912

Existing credentials are invalidated: clients must log in again once.
"""

import sqlalchemy as sa
from alembic import op

revision = "a626b1c8d023"
down_revision = "a625f0b7c912"
branch_labels = None
depends_on = None


def _clear_tokens() -> None:
    for table in ("users_refresh_token", "users_access_token"):
        op.execute(sa.table(table).delete())


def upgrade() -> None:
    _clear_tokens()
    with op.batch_alter_table("users_refresh_token") as batch:
        batch.alter_column(
            "token", existing_type=sa.Uuid(), type_=sa.String(64), postgresql_using="token::text"
        )
    with op.batch_alter_table("users_access_token") as batch:
        batch.alter_column("token", existing_type=sa.String(43), type_=sa.String(64))


def downgrade() -> None:
    # Digests cannot be restored to UUIDs or bearer secrets.
    _clear_tokens()
    with op.batch_alter_table("users_refresh_token") as batch:
        batch.alter_column(
            "token", existing_type=sa.String(64), type_=sa.Uuid(), postgresql_using="token::uuid"
        )
    with op.batch_alter_table("users_access_token") as batch:
        batch.alter_column("token", existing_type=sa.String(64), type_=sa.String(43))
