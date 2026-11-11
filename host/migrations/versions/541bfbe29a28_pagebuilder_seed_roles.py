"""users_role: create pagebuilder's editorial roles (#320)

Revision ID: 541bfbe29a28
Revises: 4381e1c2ac7e
Create Date: 2026-11-10

Pagebuilder maps ``pagebuilder_editor``, ``pagebuilder_publisher`` and
``pagebuilder_approver`` to permissions in ``register_permissions``, but that
mapping lives in code only: the users admin assigns a role only once a
``users_role`` row exists, and nothing created these. This inserts each one
that is missing by name.

Unlike the ``user`` seed (``42b922de3574``) it runs on existing installs too.
No release ever created these rows, so a missing one cannot mean an admin
deleted it, and the revision runs once, so a later deletion stays deleted. A
row a host created itself (same name) is left as it is, id and description
included.

The values are inlined, not imported from ``pagebuilder.core.permissions``: a
migration must keep meaning what it meant when it was written. The ids are
``uuid5(NAMESPACE_URL, "simple_module:role:<name>")``. Downgrade removes only
the rows no user holds.
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from fastapi_users_db_sqlalchemy.generics import GUID

# revision identifiers, used by Alembic.
revision: str = "541bfbe29a28"
down_revision: str | None = "4381e1c2ac7e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_ROLES = (
    (
        uuid.UUID("e2c8518c-4ef4-5eb2-bfd5-7a269cb30626"),
        "pagebuilder_editor",
        "PageBuilder: edit pages",
    ),
    (
        uuid.UUID("5e0cc30a-c719-5ca3-919a-55a512f27bea"),
        "pagebuilder_publisher",
        "PageBuilder: edit and publish pages",
    ),
    (
        uuid.UUID("514a9fde-1566-5e5f-9584-c3bd5b4be548"),
        "pagebuilder_approver",
        "PageBuilder: edit, publish and approve pages",
    ),
)

_role = sa.table(
    "users_role",
    sa.column("id", GUID()),
    sa.column("name", sa.String(64)),
    sa.column("description", sa.String(255)),
)
_user_role = sa.table("users_user_role", sa.column("role_id", GUID()))


def upgrade() -> None:
    bind = op.get_bind()
    present = set(
        bind.execute(
            sa.select(_role.c.name).where(_role.c.name.in_([name for _id, name, _d in _ROLES]))
        ).scalars()
    )
    for role_id, name, description in _ROLES:
        if name not in present:
            bind.execute(_role.insert().values(id=role_id, name=name, description=description))


def downgrade() -> None:
    # Never delete a role a user holds; a host's own row (another id) is not ours.
    bind = op.get_bind()
    for role_id, _name, _description in _ROLES:
        bind.execute(
            _role.delete().where(
                _role.c.id == role_id,
                ~sa.exists().where(_user_role.c.role_id == role_id),
            )
        )
