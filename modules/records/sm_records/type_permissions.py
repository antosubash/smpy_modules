"""Per-type permissions in the role editor — ``PermissionRegistry.add_source``.

Every record type has a permission of its own, ``records.type.<key>``, listed
under the "records" group next to the three static ones. Granting it (to a
role or a user, host-wide) admits the holder to that type's records even
when its ``allowed_roles`` name none of their roles; the rule itself is
:func:`sm_records.services._access.role_blocked`. Its label names the type and,
for a narrowed one, the roles ``allowed_roles`` lets in — which is how the
narrowing became visible in the role editor at all (upstream #334).

The framework's source is a **sync** callable read on every request, so it
must not touch the database. :class:`TypePermissions` is the in-memory cache
it reads, and :func:`refresh` fills it on the request path — through
:mod:`sm_records._permission_sync` — on the same terms the sidebar always had:
on demand after a type write in this process (:func:`mark_dirty`), otherwise
at most every ``menu_refresh_seconds``, which is how a second worker
converges. A changed list calls ``invalidate_source``; an unchanged one leaves
the registry's caches warm.

**Tenancy.** Roles and the role editor are host-wide, so the list is every
tenant's types, read under the framework's ``all_tenants()`` waiver, and a
key two tenants share is one permission that applies in both. On a
multi-tenant host the entries carry no label: the label of one tenant's type
is not something another tenant's administrator should be shown as the name
of theirs, and the key is what the grant actually names.

A failed read keeps the previous list and logs; the role editor one refresh
out of date is a much smaller problem than a request that fails to build it.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from sqlalchemy import select

from sm_records import constants
from sm_records._cross_tenant import read_all
from sm_records.models import RecordType
from sm_records.services._access import type_permission
from sm_records.settings import RecordsSettings
from sm_records.tenancy import TenancyMode

if TYPE_CHECKING:  # pragma: no cover - imports for typing only
    from simple_module_core.permissions import PermissionRegistry

__all__ = ["TypePermissions", "label_for", "load_entries", "refresh"]

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class TypePermissions:
    """The source's cache, owned by the module instance (one per process)."""

    registry: PermissionRegistry | None = None
    entries: list[tuple[str, str]] = field(default_factory=list)
    dirty: bool = False
    synced_at: float = 0.0
    ambiguous: bool = False  # a mounted request with no tenancy answer was seen (#210)

    def __call__(self) -> Iterable[str | tuple[str, str]]:
        """The provider handed to ``add_source``: keys, labelled where it may."""
        return [key if not label else (key, label) for key, label in self.entries]

    def register(self, registry: PermissionRegistry) -> None:
        self.registry = registry
        registry.add_source(constants.PERM_GROUP, self)

    def mark_dirty(self) -> None:
        self.dirty = True


def label_for(label_plural: str, key: str, allowed_roles: list[str]) -> str:
    """What the role editor shows for one type's permission.

    English and literal: a source supplies finished labels, with no catalogue
    lookup on the framework's side. The roles are the type's ``allowed_roles``
    — the narrowing this permission widens — so the editor says which roles
    already reach the type without the grant.
    """
    name = label_plural or key
    if not allowed_roles:
        return f"Records: {name}"
    return f"Records: {name} (restricted to {', '.join(sorted(allowed_roles))})"


async def load_entries(db_state: Any, *, labelled: bool) -> list[tuple[str, str]]:
    """``(permission, label)`` for every type in every tenant, sorted by key.

    ``labelled=False`` (multi-tenant) leaves every label empty."""
    stmt = select(RecordType.key, RecordType.label_plural, RecordType.allowed_roles)
    async with db_state.session_factory() as session:
        rows = (await read_all(session, stmt)).all()
    entries: dict[str, str] = {}
    for key, label_plural, allowed in rows:
        label = label_for(label_plural, key, list(allowed or [])) if labelled else ""
        entries.setdefault(type_permission(key), label)
    return sorted(entries.items())


async def refresh(module: Any, *, force: bool = False) -> bool:
    """Re-read the types into the source's cache, if it is time to.

    Returns whether a read happened. ``force`` is the startup read; otherwise
    a type write in this process (``dirty``) or ``menu_refresh_seconds``
    since the last read. ``0`` reads on every request the middleware covers.
    """
    source: TypePermissions = module.type_permissions
    db_state = module.db
    if source.registry is None or db_state is None:
        return False
    now = time.monotonic()
    if not force and not source.dirty:
        settings = module.settings or RecordsSettings()
        if now - source.synced_at < settings.menu_refresh_seconds:
            return False
    source.synced_at = now
    source.dirty = False
    # A mounted app the framework has no answer for (#210) may be serving
    # many tenants: latched by the middleware, and unlabelled from then on.
    single = getattr(module, "tenancy_mode", TenancyMode.SINGLE) is TenancyMode.SINGLE
    labelled = single and not source.ambiguous
    try:
        entries = await load_entries(db_state, labelled=labelled)
    except Exception:
        logger.warning(
            "records: could not read the types for the role editor; keeping the previous list",
            exc_info=True,
        )
        return False
    if entries != source.entries:
        source.entries = entries
        source.registry.invalidate_source(constants.PERM_GROUP)
    return True
