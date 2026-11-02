"""Who the harness's caller is: a header-driven user, permission set and tenant.

Stands in for ``simple_module_auth``. Split from :mod:`tests.support.app_harness` along
the seam between the app the harness builds and the identity it hands that app;
the harness re-exports everything here, so no test needs to know this module
exists.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

USER_HEADER = "X-Test-User"
PERMS_HEADER = "X-Test-Perms"
TEST_TENANT_HEADER = "X-Test-Tenant"
"""Sets the stub user's ``tenant_id``; the framework's own header is
``X-Tenant-ID`` (``TENANT_HEADER``), read only in ``tenancy="multi"``."""

ADMIN_PERMS = ("*",)
"""The wildcard the ``admin`` role resolves to."""


def as_user(user_id: str, perms: tuple[str, ...] | list[str], tenant: str | None = None):
    """Headers that make a request come from ``user_id`` holding exactly ``perms``.

    No headers at all leaves the request anonymous, which ``RequiresPermission``
    turns into a 401 as the framework's real auth middleware would.
    """
    headers = {USER_HEADER: user_id, PERMS_HEADER: ",".join(perms)}
    if tenant is not None:
        headers[TEST_TENANT_HEADER] = tenant
    return headers


def user_uuid(user_id: str) -> str:
    """The stable UUID a header user id maps to: real user ids are UUIDs, and
    the permissions module's checker casts ``user.id`` before any role check."""
    return str(uuid.uuid5(uuid.NAMESPACE_DNS, user_id))


class HeaderAuthMiddleware(BaseHTTPMiddleware):
    """``X-Test-User`` / ``X-Test-Perms`` become ``request.state.user`` and the
    resolved permission set the framework's checker reads."""

    async def dispatch(self, request: Request, call_next):  # type: ignore[override]
        raw_user = request.headers.get(USER_HEADER)
        if raw_user is not None:
            raw_perms = request.headers.get(PERMS_HEADER, "")
            perms = {p.strip() for p in raw_perms.split(",") if p.strip()}
            request.state.user = SimpleNamespace(
                id=user_uuid(raw_user),
                email=f"{raw_user}@example.com",
                roles=[],
                # ``X-Test-Tenant`` is the user row's ``tenant_id``; absent, the
                # account has none - the bootstrap admin's case.
                tenant_id=request.headers.get(TEST_TENANT_HEADER),
                scopes=None,
            )
            request.state.resolved_permissions = perms
        return await call_next(request)
