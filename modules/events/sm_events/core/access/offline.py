"""A user's rights with no request of theirs: the principal a private feed or an import acts as.

The framework resolves permissions only for the principal of the request in hand. A private
feed is fetched by a calendar client that sends no session, yet must show exactly what the
token's owner may see *now*. So this composes the framework's public pieces, the same ones
``RequiresPermission`` uses (``simple_module_hosting.permissions.resolve_principal_permissions``),
over the owner's *current* account:

* the user directory: the account must exist, be active and report its roles (a provider that
  keeps roles in the identity provider reports ``None``, and then nothing can be derived);
* on a multi-tenant host, membership of the tenant (``tenant_member_ids``; no membership store
  is nobody, never everybody);
* the role map and every grant source of ``app.state.sm.permissions``.

**Fails closed**: every doubt answers ``None``, and the feed route answers that as it answers
any refusal.

**A known gap** (upstream issue): the membership role the tenants resolver adds to a live
request (``tenant:<role>``, see :func:`simple_module_core.tenancy.tenant_role`) has no public
read, so it is left out here. That can only *narrow* what a feed serves: a user whose
permissions come only from their membership role gets an empty feed, never one they should not
have. Principals holding rights through platform roles or grant sources are unaffected.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from fastapi import Request
from simple_module_core.app_state import get_services
from simple_module_core.resources import ResourcePrincipal
from simple_module_core.tenancy import tenant_member_ids
from simple_module_core.user_directory import get_user_directory
from simple_module_hosting.permissions import resolve_principal_permissions

from sm_events.core.tenancy import DEFAULT_TENANT, TenancyMode, mode_of, request_mode

__all__ = ["OfflineUser", "offline_principal"]


@dataclass(frozen=True)
class OfflineUser:
    """The few attributes ``resolve_principal_permissions`` reads, as ``UserContext`` has them.
    No scope cap and no credential requirement: this is an account, not a token."""

    id: str
    roles: tuple[str, ...]
    tenant_id: str
    permissions: tuple[str, ...] = ()
    scopes: None = None
    required_permission: None = None


def _everyone_is_in(app: Any, tenant_id: str, request: Request | None) -> bool:
    """Whether the tenant is the one tenant of a single-tenant host, decided as the request
    paths do (``unscoped_single``): the mode is per request (a mounted app the framework has no
    answer for may be single in name only), and a tenant something upstream resolved that is
    not the default means the shortcut is off, so a wrong ``single`` fails closed.

    With no request (a worker) there is nothing per-request to ask: only the app's stored
    SINGLE mode with the default tenant may skip the lookup."""
    if tenant_id != DEFAULT_TENANT:
        return False
    stored = mode_of(app)
    if request is None:
        return stored is TenancyMode.SINGLE
    if request_mode(request, stored) is not TenancyMode.SINGLE:
        return False
    return getattr(request.state, "tenant_id", None) in (None, DEFAULT_TENANT)


async def _is_member(
    app: Any, db: Any, user_id: str, tenant_id: str, request: Request | None
) -> bool:
    if _everyone_is_in(app, tenant_id, request):
        return True  # one tenant: every active account is in it
    members = await tenant_member_ids(app, db, tenant_id, [user_id])
    return members is not None and user_id in members


async def offline_principal(
    app: Any, db: Any, *, user_id: str, tenant_id: str, request: Request | None
) -> ResourcePrincipal | None:
    """The principal ``user_id`` is in ``tenant_id`` right now, or ``None``.

    ``None`` for an unknown or deactivated account, roles the directory cannot report, a user
    who is not a member of the tenant (or a multi-tenant host with no way to tell), and a
    host with no permission registry. ``request`` is handed to the grant sources, which take
    one; it is the feed request itself, anonymous, and a source must go by the ``user`` it is
    given. ``None`` (a worker) still resolves; grant sources then get a bare request."""
    found = (await get_user_directory(app).get_many(db, [user_id], with_roles=True)).get(user_id)
    if found is None or not found.is_active or found.roles is None:
        return None
    if not await _is_member(app, db, user_id, tenant_id, request):
        return None
    services = get_services(app)
    registry = getattr(services, "permissions", None)
    if registry is None:
        return None
    user = OfflineUser(id=user_id, roles=tuple(found.roles), tenant_id=tenant_id)
    bare = request or Request(
        {"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"}
    )
    held = await resolve_principal_permissions(bare, user, registry)
    return ResourcePrincipal(user_id=user_id, permissions=frozenset(held))
