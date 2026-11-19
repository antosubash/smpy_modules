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

**A known gap** (upstream simple_module_python #1005: no principal outside a request): the
membership role the tenants resolver adds to a live
request (``tenant:<role>``, see :func:`simple_module_core.tenancy.tenant_role`) has no public
read, so it is left out here. That can only *narrow* what a feed serves: a user whose
permissions come only from their membership role gets an empty feed, never one they should not
have. Principals holding rights through platform roles or grant sources are unaffected.
"""

from __future__ import annotations

from collections.abc import Collection
from dataclasses import dataclass
from typing import Any

from fastapi import Request
from simple_module_core.app_state import get_services
from simple_module_core.resources import ResourcePrincipal
from simple_module_core.tenancy import tenant_member_ids
from simple_module_core.user_directory import DirectoryUser, get_user_directory
from simple_module_hosting.permissions import resolve_principal_permissions

from sm_events.calendar.plugins.extension_types import SourceViewer
from sm_events.core.tenancy import DEFAULT_TENANT, TenancyMode, mode_of, request_mode

__all__ = ["OfflineAccount", "OfflineUser", "feed_viewer", "offline_accounts", "offline_principal"]


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


async def _members(
    app: Any, db: Any, user_ids: list[str], tenant_id: str, request: Request | None
) -> set[str]:
    """Which of ``user_ids`` are in the tenant: all of them on a single-tenant host, else the
    membership store's answer, and nobody when there is no store (fail closed)."""
    if _everyone_is_in(app, tenant_id, request):
        return set(user_ids)
    members = await tenant_member_ids(app, db, tenant_id, user_ids)
    return set() if members is None else members & set(user_ids)


@dataclass(frozen=True)
class OfflineAccount:
    """An account as the offline principal sees it: the directory's record (address, name,
    ``email_verified``) and the principal that account holds in the tenant right now."""

    user: DirectoryUser
    principal: ResourcePrincipal
    roles: tuple[str, ...]


async def offline_accounts(
    app: Any, db: Any, *, user_ids: Collection[str], tenant_id: str, request: Request | None
) -> dict[str, OfflineAccount]:
    """:func:`offline_principal` for many users at once, on one directory read
    (``get_many(..., with_roles=True)``) and one membership read. A user missing from the answer
    is unknown, deactivated, without reportable roles, not a member, or the host has no
    permission registry: the caller cannot tell which, and must treat all as "no"."""
    ids = sorted(set(user_ids))
    if not ids:
        return {}
    registry = getattr(get_services(app), "permissions", None)
    if registry is None:
        return {}
    found = await get_user_directory(app).get_many(db, ids, with_roles=True)
    live = {i: u for i, u in found.items() if u.is_active and u.roles is not None}
    if not live:
        return {}
    bare = request or Request(
        {"type": "http", "app": app, "headers": [], "method": "GET", "path": "/"}
    )
    accounts: dict[str, OfflineAccount] = {}
    for user_id in sorted(await _members(app, db, sorted(live), tenant_id, request)):
        record = live[user_id]
        roles = tuple(record.roles or ())
        user = OfflineUser(id=user_id, roles=roles, tenant_id=tenant_id)
        held = await resolve_principal_permissions(bare, user, registry)
        principal = ResourcePrincipal(user_id=user_id, permissions=frozenset(held))
        accounts[user_id] = OfflineAccount(user=record, principal=principal, roles=roles)
    return accounts


async def offline_principal(
    app: Any, db: Any, *, user_id: str, tenant_id: str, request: Request | None
) -> ResourcePrincipal | None:
    """The principal ``user_id`` is in ``tenant_id`` right now, or ``None``.

    ``None`` for an unknown or deactivated account, roles the directory cannot report, a user
    who is not a member of the tenant (or a multi-tenant host with no way to tell), and a
    host with no permission registry. ``request`` is handed to the grant sources, which take
    one; it is the feed request itself, anonymous, and a source must go by the ``user`` it is
    given. ``None`` (a worker) still resolves; grant sources then get a bare request."""
    got = await offline_accounts(app, db, user_ids=[user_id], tenant_id=tenant_id, request=request)
    return got[user_id].principal if user_id in got else None


async def feed_viewer(
    app: Any, db: Any, *, user_id: str, tenant_id: str, request: Request | None
) -> SourceViewer | None:
    """The same person as :func:`offline_principal`, as a plugin source sees a viewer: roles from
    the directory (a source may narrow by role), the permissions the principal holds, and the
    role map. ``None`` under every doubt, and the feed then calls no plugin source for them."""
    got = await offline_accounts(app, db, user_ids=[user_id], tenant_id=tenant_id, request=request)
    account = got.get(user_id)
    if account is None:
        return None
    registry = get_services(app).permissions
    role_map = getattr(registry, "role_map", None)
    return SourceViewer(
        user_id=user_id,
        roles=account.roles,
        permissions=account.principal.permissions,
        role_map=dict(role_map) if role_map is not None else None,
    )
