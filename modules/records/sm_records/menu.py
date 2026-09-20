"""Per-type entries in the admin sidebar — built here, and kept in sync here.

A Record Type with ``show_in_menu`` set gets its own sidebar item, labelled
with its plural and pointing at its record list, next to the module's
"Records" hub entry. The hub is never touched: it is how every *other* type
is reached, and a sidebar with an item per type would be unusable on an
install with thirty of them.

The awkward part is that types are created at runtime and the framework's
``MenuRegistry`` is not. It is filled once, during app construction, by each
module's ``register_menu_items`` hook; it has ``add``/``add_many`` and no
remove, no provider hook and no invalidation anyone else can reach. Meanwhile
``InertiaLayoutDataMiddleware`` calls ``get_for_user`` on that one instance for
every request, so whatever is in it *is* the sidebar.

So this module keeps the registry's contents honest itself:

* :func:`type_menu_items` turns types into items and is pure — the whole of
  what an entry looks like, testable without a registry or a database.
* :func:`sync_type_menu` replaces the items this module put there last time
  with the ones it wants now. It is the only place that reaches inside the
  registry, and it identifies *our* items by the list we kept, never by URL:
  a host that adds its own ``/admin/records/...`` entry must survive a sync.
* :func:`refresh` decides when that is worth doing — on demand after a type
  write, and otherwise at most every ``menu_refresh_seconds``, which is what
  makes a second worker process converge without a restart.

A read that fails (a boot before the migration, a transient error) leaves the
previous items in place and logs; a sidebar one refresh out of date is a much
smaller problem than a request that 500s to rebuild it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from sqlalchemy import select

from sm_records import constants
from sm_records.models import RecordType

if TYPE_CHECKING:  # pragma: no cover - imports for typing only
    from fastapi import FastAPI

    from sm_records.module import RecordsModule

__all__ = [
    "MENU_CHANGING_FIELDS",
    "MenuType",
    "affects_menu",
    "load_menu_types",
    "mark_dirty",
    "refresh",
    "sync_type_menu",
    "type_menu_items",
]

logger = logging.getLogger(__name__)

MENU_CHANGING_FIELDS = frozenset({"label_plural", "icon", "allowed_roles", "show_in_menu"})
"""The columns of a type an entry is built from. A ``PUT`` that touches none of
them cannot have changed the sidebar, so it does not mark it stale — ``key`` is
absent because it is immutable (``services._type_update``), and ``fields`` and
everything else about the schema never reach the sidebar at all."""


@dataclass(frozen=True, slots=True)
class MenuType:
    """The four columns an entry needs, and nothing else.

    :func:`load_menu_types` selects exactly these rather than whole
    ``RecordType`` rows: the read happens on the request path (see
    :func:`refresh`), and the schema JSON — by far the widest column on the
    table — has nothing to do with navigation. Being a plain frozen record
    also means :func:`type_menu_items` can be tested without a database.
    """

    key: str
    label_plural: str
    icon: str | None
    allowed_roles: list[str]


def type_menu_items(types: Sequence[MenuType]) -> list[MenuItem]:
    """The sidebar items for ``types``, in the order they should be inserted.

    Sorted by the plural label, case-folded, because the registry sorts by
    ``order`` alone and Python's sort is stable: every per-type item carries
    the same ``MENU_ORDER_TYPE``, so insertion order *is* the order they
    render in, and alphabetical is the only arrangement an editor can predict.

    ``roles`` is the type's own ``allowed_roles``, deliberately. Menu role
    filtering is a plain intersection with no admin bypass — which is why the
    hub entry lists no roles at all — but here the narrowing matches what the
    page behind the link actually does: ``services._common.role_blocked`` has
    no wildcard either, so a caller the type excludes gets a 403 from the
    record list. Showing them a link to it would be the surprising choice.
    An empty list means every authenticated user sees the entry, and the
    view's own ``records.view`` permission still gates the page.
    """
    ordered = sorted(types, key=lambda rtype: (rtype.label_plural or rtype.key).casefold())
    return [
        MenuItem(
            label=rtype.label_plural,
            url=f"{constants.VIEW_PREFIX}/{rtype.key}",
            icon=rtype.icon or constants.MENU_ICON,
            order=constants.MENU_ORDER_TYPE,
            section=MenuSection.ADMIN_SIDEBAR,
            group=constants.MENU_GROUP,
            roles=list(rtype.allowed_roles or []),
        )
        for rtype in ordered
    ]


async def load_menu_types(db_state: Any) -> list[MenuType]:
    """Every type that asked for an entry, on a session of this function's own.

    ``db_state`` is the host's ``DatabaseState`` (``app.state.sm.db``), which
    the module parks on itself at startup — the same route
    :mod:`sm_records.health` takes, and for the same reason: this runs from
    middleware, before the route that owns the request's session has one, and
    borrowing that session would tie a sidebar read to a transaction the
    request may still roll back.

    No soft-delete concerns: types are hard-deleted, so a row here is a type
    that exists.
    """
    stmt = (
        select(
            RecordType.key,
            RecordType.label_plural,
            RecordType.icon,
            RecordType.allowed_roles,
        )
        .where(RecordType.show_in_menu.is_(True))
        .order_by(RecordType.key)
    )
    async with db_state.session_factory() as session:
        rows = (await session.execute(stmt)).all()
    return [
        MenuType(key=key, label_plural=label, icon=icon, allowed_roles=list(roles or []))
        for key, label, icon, roles in rows
    ]


def sync_type_menu(
    registry: MenuRegistry,
    types: Sequence[MenuType],
    *,
    previous: Sequence[MenuItem] = (),
) -> list[MenuItem]:
    """Put exactly ``types``' items in ``registry``, and return what was added.

    ``previous`` is what this function returned last time — the caller (the
    module instance) keeps it. Removal is by object identity against that
    list and never by URL or by value, so a host that contributed its own
    ``/admin/records/...`` entry keeps it, and so does this module's hub item.

    The registry has no remove; upstream: antosubash/simple_module_python#340
    (MenuRegistry: no way to remove items or contribute them dynamically).
    Until that lands, the splice below is the whole of this module's reach
    into framework internals: one function, and it restores the registry's own
    invariant by invalidating the sorted cache it keeps beside ``_items``.
    """
    items = type_menu_items(types)
    if list(previous) == items:
        # Nothing changed — the common case on a refresh that merely aged out
        # of its TTL. Leaving the registry untouched keeps its sorted cache
        # warm for the request that is about to read it.
        return list(previous)
    ours = {id(item) for item in previous}
    registry._items[:] = [item for item in registry._items if id(item) not in ours]
    registry._invalidate()
    registry.add_many(items)
    return items


def affects_menu(changes: Mapping[str, Any]) -> bool:
    """Whether an accepted set of type changes can have moved the sidebar."""
    return not MENU_CHANGING_FIELDS.isdisjoint(changes)


def mark_dirty(app: FastAPI) -> None:
    """Note that the sidebar is stale, from inside a request.

    Called by the endpoints after a type write, never by a service: a service
    takes a session and knows nothing about the app, the registry or the
    module instance, and giving it any of the three to keep a menu current
    would be the wrong trade by a distance.

    It only marks. The write that made the menu stale has not committed yet
    (``CommitBeforeResponseMiddleware`` does that after the response starts),
    so re-reading here would read the old rows; the next request that renders
    a sidebar does the work, and finds the committed row.
    """
    module = getattr(app.state, constants.MODULE_ATTR, None)
    if module is not None:
        module.mark_menu_dirty()


async def refresh(module: RecordsModule, *, force: bool = False) -> bool:
    """Re-read the types and re-sync the registry, if it is time to.

    Returns whether a read actually happened — which is what the tests assert
    against, and what keeps the TTL honest.

    Three ways to be "time to": ``force`` (the one sync at startup), a type
    write earlier in this process (:func:`mark_dirty`), or more than
    ``menu_refresh_seconds`` since the last read. The last is what a host
    running several workers needs: the process that served the ``PUT`` marks
    itself, and the others notice within the window rather than at the next
    restart. ``0`` means every request, which is the setting for an install
    that would rather pay a query per page than ever show a stale sidebar.

    A failed read is logged and otherwise ignored: the previously synced items
    stay in the registry, and the clock is reset so a database that is down —
    or a boot that got here before the migration did — costs one query per
    window rather than one per request. The dirty flag is cleared with it for
    the same reason; the window will re-read anyway.
    """
    registry = module.menu_registry
    db_state = module.db
    if registry is None or db_state is None:
        # No ``register_menu_items`` (a harness that mounts the routers by
        # hand) or no database yet (a request that raced the lifespan).
        return False
    now = time.monotonic()
    if not force and not module._menu_dirty:
        settings = module.settings or _default_settings()
        if now - module._menu_synced_at < settings.menu_refresh_seconds:
            return False
    module._menu_synced_at = now
    module._menu_dirty = False
    try:
        types = await load_menu_types(db_state)
    except Exception:
        logger.warning(
            "records: could not read the sidebar types; keeping the previous entries",
            exc_info=True,
        )
        return False
    module._type_menu_items = sync_type_menu(registry, types, previous=module._type_menu_items)
    return True


def _default_settings():
    from sm_records.settings import RecordsSettings

    return RecordsSettings()
