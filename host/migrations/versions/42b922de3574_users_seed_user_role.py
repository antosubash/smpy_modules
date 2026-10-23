"""users_role: seed the standard ``user`` role (framework 0.0.37)

Revision ID: 42b922de3574
Revises: 307543b6146a
Create Date: 2026-10-23

The framework's own revision ``b5018b617142`` (#488), ported unchanged into
this host's history, since the host owns its migrations.

Self-registered accounts are given the ``user`` role, which the manager looks
up rather than creates (a role an admin deleted must stay deleted). Nothing
inserted it on a fresh install, so every signup came out with no role and no
permissions. This inserts it, but only on a fresh install: when
``users_user`` has no rows and no role with that name or id exists.

An install that already has users is left alone. There, a missing ``user``
role most likely means an admin deleted it on purpose, and re-inserting it on
upgrade would silently hand signups (and everything mapped onto ``user``) the
access that admin removed.

The values are inlined, not imported from ``users.constants``: a migration
must keep meaning what it meant when it was written. Downgrade is a no-op: the
role may be assigned to users by then.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy.generics import GUID

# revision identifiers, used by Alembic.
revision: str = "42b922de3574"
down_revision: str | None = "307543b6146a"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_USER_ROLE_ID = uuid.UUID("00000000-0000-0000-0000-000000000002")
_USER_ROLE_NAME = "user"
_USER_ROLE_DESCRIPTION = "Standard user"

_role = sa.table(
    "users_role",
    sa.column("id", GUID()),
    sa.column("name", sa.String(64)),
    sa.column("description", sa.String(255)),
)
_user = sa.table("users_user", sa.column("id", GUID()))


def upgrade() -> None:
    bind = op.get_bind()
    if bind.execute(sa.select(sa.func.count()).select_from(_user)).scalar_one():
        return  # an existing install: never undo an admin's deletion
    existing = bind.execute(
        sa.select(sa.func.count())
        .select_from(_role)
        .where(sa.or_(_role.c.name == _USER_ROLE_NAME, _role.c.id == _USER_ROLE_ID))
    ).scalar_one()
    if existing:
        return
    bind.execute(
        _role.insert().values(
            id=_USER_ROLE_ID, name=_USER_ROLE_NAME, description=_USER_ROLE_DESCRIPTION
        )
    )


def downgrade() -> None:
    # Never delete a role that may be assigned to users.
    pass
