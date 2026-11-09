"""Enforce case-insensitive login identities without changing accounts (#731). (framework 0.0.43)

Revision ID: e731a1b2c3d4
Revises: a738c2e4f601
"""

import sqlalchemy as sa
from alembic import op

revision = "e731a1b2c3d4"
down_revision = "a738c2e4f601"
branch_labels = None
depends_on = None

_TABLE = "users_user"
_INDEX = "ix_users_user_email_lower"


def upgrade() -> None:
    users = sa.table(_TABLE, sa.column("email"))
    email = users.c.email
    lowered = sa.func.lower(email)
    conflicts = list(
        op.get_bind()
        .execute(sa.select(lowered).group_by(lowered).having(sa.func.count() > 1))
        .scalars()
    )
    if conflicts:
        # Migration output lands in deploy logs: masked addresses only.
        masked = ", ".join(f"{c[:1]}***@{c.partition('@')[2]}" for c in conflicts[:20])
        raise RuntimeError(
            f"Cannot enforce case-insensitive email uniqueness: {len(conflicts)} email "
            f"address(es) are used by more than one account in different letter case "
            f"({masked}{' and more' if len(conflicts) > 20 else ''}). List them with: "
            "SELECT id, email FROM users_user WHERE lower(email) IN (SELECT lower(email) "
            "FROM users_user GROUP BY lower(email) HAVING count(*) > 1); give each account "
            "a distinct email and retry. No accounts were merged or deleted."
        )
    op.drop_index(_INDEX, table_name=_TABLE, if_exists=True)
    # Hand-written: SQLite autogenerate cannot reflect expression indexes.
    op.create_index(_INDEX, _TABLE, [sa.text("lower(email)")], unique=True)


def downgrade() -> None:
    op.drop_index(_INDEX, table_name=_TABLE)
    op.create_index(_INDEX, _TABLE, [sa.text("lower(email)")])
