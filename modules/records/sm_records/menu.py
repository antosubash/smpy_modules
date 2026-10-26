"""Per-type entries in the admin sidebar — a ``MenuRegistry`` provider.

A Record Type with ``show_in_menu`` set gets its own sidebar item, labelled
with its plural and pointing at its record list, next to the module's static
"All record types" hub entry. The hub is never touched: it is how every
*other* type is reached, and a sidebar with an item per type would be
unusable on an install with thirty of them.

Types are created at runtime, and since framework 0.0.36 (upstream #340) the
registry takes a provider for exactly that: :func:`type_menu_provider` is
called by ``InertiaLayoutDataMiddleware`` for every request, after auth and
tenant resolution, and returns this request's items. So the entries are the
**request's own tenant's** types — on a multi-tenant host too, where the old
process-wide registry could only show none (it had no request to ask).

* :func:`type_menu_items` turns types into items and is pure.
* :func:`visible_items` keeps the ones this caller may open: the same
  :func:`~sm_records.services._access.role_blocked` the record list applies,
  per-type grants included, and ``records.view`` — an entry that 403s on click
  is worse than no entry at all.
* :class:`TypeMenuCache` holds each tenant's types for at most
  ``menu_refresh_seconds``, keyed by tenant and never shared between them; a
  type write in this process drops it at once (:func:`mark_dirty`), which is
  the half a second worker gets from the window instead.

A read that fails logs and contributes nothing; a sidebar without the per-type
entries is a much smaller problem than a page that 500s to build one.
"""

from __future__ import annotations

import logging
import time
from collections import OrderedDict
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from simple_module_core.menu import MenuItem, MenuSection
from simple_module_core.permissions import grants
from simple_module_hosting.permissions import ensure_resolved_permissions
from sqlalchemy import select

from sm_records import constants
from sm_records.models import RecordType
from sm_records.services._access import caller_access, request_role_map, role_blocked
from sm_records.settings import RecordsSettings
from sm_records.tenancy import resolve_public, tenant_scope

if TYPE_CHECKING:  # pragma: no cover - imports for typing only
    from fastapi import FastAPI
    from starlette.requests import Request

__all__ = [
    "MENU_CHANGING_FIELDS",
    "MenuType",
    "TypeMenuCache",
    "affects_menu",
    "load_menu_types",
    "mark_dirty",
    "type_menu_items",
    "type_menu_provider",
    "visible_items",
]

logger = logging.getLogger(__name__)

MENU_CHANGING_FIELDS = frozenset({"label_plural", "icon", "allowed_roles", "show_in_menu"})
"""The columns of a type an entry — or its role-editor label — is built from.
A ``PUT`` that touches none of them cannot have changed either, so it marks
nothing stale. ``key`` is absent because it is immutable."""

MAX_CACHED_TENANTS = 256
"""Tenants whose sidebar types one worker keeps; the least recently read goes first."""


@dataclass(frozen=True, slots=True)
class MenuType:
    """The four columns an entry needs, and nothing else — the read is on the
    request path, and the schema JSON has nothing to do with navigation."""

    key: str
    label_plural: str
    icon: str | None
    allowed_roles: list[str]


def type_menu_items(types: Sequence[MenuType]) -> list[MenuItem]:
    """The sidebar items for ``types``, sorted by plural label, case-folded.

    Every per-type item carries the same ``MENU_ORDER_TYPE`` and the
    registry's sort is stable, so this order *is* the order they render in.
    They carry no ``roles``: who sees one is :func:`visible_items`' decision,
    made per caller, because a menu role filter cannot express a per-type
    grant.
    """
    ordered = sorted(types, key=lambda rtype: (rtype.label_plural or rtype.key).casefold())
    return [
        MenuItem(
            label=rtype.label_plural,
            url=f"{constants.VIEW_PREFIX}/{rtype.key}",
            icon=rtype.icon or constants.MENU_ICON,
            order=constants.MENU_ORDER_TYPE,
            section=MenuSection.ADMIN_SIDEBAR,
            group=constants.MENU_GROUP_TYPES,
            group_key=constants.MENU_GROUP_KEY_TYPES,
        )
        for rtype in ordered
    ]


def visible_items(
    types: Sequence[MenuType],
    user: Any,
    held: set[str],
    role_map: Mapping[str, Any] | None = None,
) -> list[MenuItem]:
    """The items of ``types`` this caller may open: ``records.view``, and not
    narrowed out (an ``admin`` included — narrowing has no wildcard)."""
    if user is None or not grants(held, constants.PERM_VIEW):
        return []
    caller = caller_access(user, held, role_map)
    return type_menu_items([rtype for rtype in types if not role_blocked(rtype, caller)])


async def load_menu_types(db_state: Any) -> list[MenuType]:
    """The bound tenant's types that asked for an entry, on a session of its own.

    ``db_state`` is the host's ``DatabaseState``: this runs in the layout
    middleware, before any route has a session, and borrowing a request's
    would tie a sidebar read to a transaction it may still roll back. Types
    are hard-deleted, so there is no trash to exclude.
    """
    stmt = (
        select(RecordType.key, RecordType.label_plural, RecordType.icon, RecordType.allowed_roles)
        .where(RecordType.show_in_menu.is_(True))
        .order_by(RecordType.key)
    )
    async with db_state.session_factory() as session:
        rows = (await session.execute(stmt)).all()
    return [
        MenuType(key=key, label_plural=label, icon=icon, allowed_roles=list(roles or []))
        for key, label, icon, roles in rows
    ]


class TypeMenuCache:
    """Each tenant's sidebar types, for at most ``menu_refresh_seconds``.

    Keyed by tenant id, and a lookup only ever returns the entry of the tenant
    it was asked for — nothing read for one tenant reaches another.
    """

    def __init__(self) -> None:
        self._entries: OrderedDict[str, tuple[float, list[MenuType]]] = OrderedDict()

    def get(self, tenant: str, max_age: float) -> list[MenuType] | None:
        entry = self._entries.get(tenant)
        if entry is None or time.monotonic() - entry[0] >= max_age:
            return None
        self._entries.move_to_end(tenant)
        return entry[1]

    def put(self, tenant: str, types: list[MenuType]) -> None:
        self._entries[tenant] = (time.monotonic(), types)
        self._entries.move_to_end(tenant)
        while len(self._entries) > MAX_CACHED_TENANTS:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        self._entries.clear()


async def tenant_menu_types(module: Any, tenant: str) -> list[MenuType]:
    """``tenant``'s sidebar types, from the cache or a read in its scope."""
    settings = module.settings or RecordsSettings()
    cached = module.menu_cache.get(tenant, settings.menu_refresh_seconds)
    if cached is not None:
        return cached
    with tenant_scope(tenant):
        types = await load_menu_types(module.db)
    module.menu_cache.put(tenant, types)
    return types


async def type_menu_provider(module: Any, request: Request) -> list[MenuItem]:
    """The provider registered with ``MenuRegistry.add_provider``.

    The tenant is :func:`~sm_records.tenancy.resolve_public`'s answer — the
    one the framework resolved, else ``default`` on a single-tenant host, else
    none (and no entries). It never raises: an unbindable tenant, a database
    that is down, a boot before the migration all mean no per-type entries.
    """
    if module.db is None or request.scope.get("path", "").startswith(constants.MENU_SKIP_PREFIXES):
        return []
    user = getattr(request.state, "user", None)
    if user is None:
        return []
    tenant = resolve_public(request)
    if tenant is None:
        return []
    try:
        types = await tenant_menu_types(module, tenant)
        held = await ensure_resolved_permissions(request)
    except Exception:
        logger.warning("records: could not read the sidebar types", exc_info=True)
        return []
    return visible_items(types, user, held, request_role_map(request))


def affects_menu(changes: Mapping[str, Any]) -> bool:
    """Whether an accepted set of type changes can have moved the sidebar
    (or a type's role-editor label)."""
    return not MENU_CHANGING_FIELDS.isdisjoint(changes)


def mark_dirty(app: FastAPI) -> None:
    """Note, from inside a request, that a type write moved the sidebar or the
    per-type permissions.

    Called by the endpoints, never by a service. It only marks: the write has
    not committed yet (the framework commits after the response starts), so
    the next request does the read and finds the committed row.
    """
    module = getattr(app.state, constants.MODULE_ATTR, None)
    if module is not None:
        module.mark_menu_dirty()
