"""Does a user still hold ``images.manage``? Asked by a worker, with no request.

The framework resolves permissions per request only: grant sources take the
``Request``, and the role map lives in the ``PermissionRegistry`` the app
builds at boot - which a Celery worker never does (plan decision 1). So a
worker re-verifies from the tables those grants are stored in:

* the user's global roles (``users``: ``users_user_role`` -> ``users_role``),
  plus their membership role in the job's tenant as ``tenant:<role>``
  (``tenants``);
* ``admin`` among them holds everything (the framework's wildcard role);
* a role overlay granting ``images.manage`` or ``*`` (``permissions``:
  ``permissions_role_permission``), or a direct grant to the user
  (``permissions_user_permission``).

The answer is ``True``/``False`` when every source could be read, and
``None`` - "cannot tell" - when one cannot: a module not installed, its table
missing, a principal from an external identity provider with no local user row,
a non-uuid id. The caller keeps the job then (``imports.access``). A role a
host maps to ``images.manage`` in code (``map_role``) rather than on the
permissions screen is invisible here; images maps none.
"""

from __future__ import annotations

import logging
import uuid
from typing import Any

from simple_module_core.permissions import WILDCARD
from simple_module_db import finalize_session
from sqlalchemy import select
from sqlalchemy.exc import SQLAlchemyError

from sm_images import constants
from sm_images.pipeline.runtime import Runtime

__all__ = ["holds_manage"]

logger = logging.getLogger(__name__)

ADMIN_ROLE = "admin"
_KEYS = (constants.PERM_MANAGE, WILDCARD)
_UNKNOWN = object()


async def _read(runtime: Runtime, stmt: Any) -> Any:
    """``stmt``'s rows, in a session of its own (a missing table must not poison
    another read), or :data:`_UNKNOWN`."""
    try:
        async with runtime.session_factory() as db:
            rows = list((await db.execute(stmt)).all())
            await finalize_session(db)
        return rows
    except SQLAlchemyError:
        logger.info("images.import.manage_right_unreadable", exc_info=True)
        return _UNKNOWN


async def _global_roles(runtime: Runtime, uid: uuid.UUID) -> Any:
    try:
        from users.models.role import Role
        from users.models.user import User
        from users.models.user_role import UserRole
    except ImportError:
        return _UNKNOWN
    known = await _read(runtime, select(User.id).where(User.id == uid))
    if known is _UNKNOWN or not known:
        return _UNKNOWN  # an external principal: its roles live elsewhere
    stmt = select(Role.name).join(UserRole, UserRole.role_id == Role.id)
    rows = await _read(runtime, stmt.where(UserRole.user_id == uid))
    return rows if rows is _UNKNOWN else {r[0] for r in rows}


async def _tenant_roles(runtime: Runtime, tenant: str, user_id: str) -> Any:
    try:
        from tenants.models import Membership
    except ImportError:
        return set()  # no memberships on this host: no tenant role to hold
    from simple_module_core.tenancy import tenant_role

    stmt = select(Membership.role).where(
        Membership.tenant_id == tenant, Membership.user_id == user_id
    )
    rows = await _read(runtime, stmt)
    if rows is _UNKNOWN:
        return rows
    out = set()
    for (role,) in rows:
        try:
            out.add(tenant_role(str(role)))
        except ValueError:
            continue
    return out


async def _granted(runtime: Runtime, uid: uuid.UUID, roles: set[str]) -> Any:
    try:
        from permissions.models import RolePermission, UserPermission
    except ImportError:
        return False  # no grants on this host beyond the code's role map
    direct = select(UserPermission.permission_key).where(
        UserPermission.user_id == uid, UserPermission.permission_key.in_(_KEYS)
    )
    rows = await _read(runtime, direct)
    if rows is _UNKNOWN or rows:
        return rows if rows is _UNKNOWN else True
    if not roles:
        return False
    overlay = select(RolePermission.role_name).where(
        RolePermission.role_name.in_(sorted(roles)), RolePermission.permission_key.in_(_KEYS)
    )
    rows = await _read(runtime, overlay)
    return rows if rows is _UNKNOWN else bool(rows)


async def holds_manage(runtime: Runtime, tenant: str, user_id: str) -> bool | None:
    """Whether ``user_id`` holds ``images.manage`` in ``tenant``; ``None`` when
    that cannot be told from here (see the module docstring)."""
    try:
        uid = uuid.UUID(str(user_id))
    except ValueError:
        return None
    global_roles = await _global_roles(runtime, uid)
    tenant_roles = await _tenant_roles(runtime, tenant, str(user_id))
    roles = {
        *(() if global_roles is _UNKNOWN else global_roles),
        *(() if tenant_roles is _UNKNOWN else tenant_roles),
    }
    if ADMIN_ROLE in roles:
        return True
    granted = await _granted(runtime, uid, roles)
    if granted is True:
        return True
    if _UNKNOWN in (global_roles, tenant_roles, granted):
        return None
    return False
