"""Who the harness's caller is: header-driven roles and tenant.

Split from :mod:`tests.app_harness` for the 300-line cap, along the seam
between the app the harness builds and the stub identity it hands that app.
Everything here is re-exported from ``app_harness`` (and from there by
``conftest``), so no test has to know this module exists.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import Request
from simple_module_core.permissions import PermissionRegistry
from simple_module_hosting.permissions import resolve_permissions
from starlette.middleware.base import BaseHTTPMiddleware

try:
    # Only present when the host also installs ``permissions`` — see
    # ``sm_records.deps``'s fallback import for why ``records`` cannot
    # require it. When it *is* installed (as in this repo's dev venv),
    # ``deps.RequiresPermission`` resolves to ``permissions.deps``'s version,
    # which (a) needs a real UUID for ``request.state.user.id`` rather than
    # this harness's plain ``"test:<roles>"`` string, and (b) queries
    # ``permissions_user_permission`` directly rather than falling back to
    # the role map when ``request.state.resolved_permissions`` is unset — so
    # both have to be provided here for the harness to behave like the real
    # request pipeline (``AuthMiddleware`` sets ``resolved_permissions``;
    # real user ids are UUIDs). Its table is created by
    # ``tests.pg_support.make_db_state``.
    import permissions.models  # noqa: F401

    _PERMISSIONS_INSTALLED = True
except ImportError:  # pragma: no cover - exercised only without `permissions`
    _PERMISSIONS_INSTALLED = False

#: Holds ``records.view`` + ``records.edit`` — the caller a ``allowed_roles``
#: test uses as the one who *should* pass.
ROLE_VIEWER = "records-viewer"
ROLE_EDITOR = "records-editor"
#: A second, distinct edit-capable role: holds the same static permission as
#: ``ROLE_EDITOR`` but is never on a type's ``allowed_roles`` list unless a
#: test puts it there — the caller who should be refused.
ROLE_EDITOR_TWO = "records-editor-two"
ROLE_MANAGER = "records-manager"
#: Registered nowhere: resolves to an empty permission set, same as any
#: role nobody mapped. Named for readability at call sites.
ROLE_NONE = "records-nobody"

TEST_TENANT_HEADER = "X-Test-Tenant"
"""Sets the stub user's ``tenant_id``; the framework's own header is
``X-Tenant-ID`` (``TENANT_HEADER``), read only in ``tenancy="multi"``."""

ADMIN = "admin"
"""Resolves to the wildcard via ``DEFAULT_ROLE_PERMISSIONS`` with no mapping
of our own needed — the case a naive membership check over a literal
permission list would miss."""


def _register_roles(registry: PermissionRegistry) -> None:
    from sm_records.constants import PERM_EDIT, PERM_MANAGE_TYPES, PERM_VIEW

    registry.map_role(ROLE_VIEWER, [PERM_VIEW])
    registry.map_role(ROLE_EDITOR, [PERM_VIEW, PERM_EDIT])
    registry.map_role(ROLE_EDITOR_TWO, [PERM_VIEW, PERM_EDIT])
    registry.map_role(ROLE_MANAGER, [PERM_VIEW, PERM_EDIT, PERM_MANAGE_TYPES])


class _HeaderAuthMiddleware(BaseHTTPMiddleware):
    """``X-Test-Roles: role-a,role-b`` becomes ``request.state.user.roles``.

    No header at all leaves the request anonymous — the harness's stand-in
    for an unauthenticated caller, which ``RequiresPermission`` turns into a
    401 exactly as the framework's real auth middleware would.
    """

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        raw = request.headers.get("X-Test-Roles")
        if raw is not None:
            roles_list = [role.strip() for role in raw.split(",") if role.strip()]
            # A real UUID when ``permissions`` is installed — its checker
            # casts ``user.id`` with ``uuid.UUID(str(...))`` before it ever
            # gets to a role check that would otherwise short-circuit that;
            # deterministic (not random) so the same header always maps to
            # the same id within a test.
            user_id = (
                str(uuid.uuid5(uuid.NAMESPACE_DNS, raw))
                if _PERMISSIONS_INSTALLED
                else f"test:{raw}"
            )
            # ``X-Test-Tenant`` is the user row's ``tenant_id`` (tenancy §K);
            # absent, the account has none — the bootstrap admin's case.
            request.state.user = SimpleNamespace(
                id=user_id,
                email="test@example.com",
                roles=roles_list,
                tenant_id=request.headers.get(TEST_TENANT_HEADER),
            )
            # Mirrors ``AuthMiddleware`` (``simple_module_hosting/middleware.py``),
            # which runs ahead of every dependency in production. Without it,
            # ``permissions.deps.RequiresPermission`` (unlike the framework's
            # own, roles-only checker) has no role-map fallback of its own and
            # treats every caller as holding nothing but direct grants.
            registry = request.app.state.sm.permissions
            request.state.resolved_permissions = resolve_permissions(
                roles_list, role_map=registry.role_map
            )
        return await call_next(request)


def roles(*names: str) -> dict[str, str]:
    """``client.get(url, headers=roles(ADMIN))`` — the one header the stub
    auth middleware reads."""
    return {"X-Test-Roles": ",".join(names)}
