"""The bounded occurrences read, for another module (a feed, a card, a widget).

The caller names the tenant and it is pinned *here*: bound with
:func:`sm_events.core.tenancy.tenant_scope` (re-entering the bound tenant is a
no-op; naming a different one raises ``TenantIsolationError``), and the read adds
an explicit ``tenant_id`` predicate besides. An invalid ``tenant_id`` raises
``ValueError`` before any SQL runs.

``viewer=None`` is the public view: an anonymous principal, so only ``public``
calendars and only ``published`` events, whatever else is asked. A viewer is
asked for explicitly, and sees what it would see in the console. The bounds are
the internal read's: a range of at most 366 days (``InvalidRange`` otherwise), at
most 2,000 items and ``truncated`` set when there were more. Never commits.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterable
from datetime import datetime

from simple_module_core.resources import ResourcePrincipal
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.calendar import occurrences as _read
from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters, OccurrencePage
from sm_events.calendar.plugins.extension_types import SourceViewer
from sm_events.core.tenancy import tenant_scope

__all__ = ["Occurrence", "OccurrencePage", "occurrences"]


def _set[T](values: Iterable[T] | None) -> frozenset[T] | None:
    return None if values is None else frozenset(values)


async def occurrences(
    session: AsyncSession,
    *,
    tenant_id: str,
    viewer: ResourcePrincipal | None,
    start: datetime,
    end: datetime,
    calendar_ids: Iterable[uuid.UUID] | None = None,
    category_ids: Iterable[uuid.UUID] | None = None,
    types: Iterable[str] | None = None,
    locale: str | None = None,
    default_locale: str = "en",
    sources: Iterable[str] | None = None,
    source_viewer: SourceViewer | None = None,
) -> OccurrencePage:
    """What ``viewer`` (``None``: the public) may see in ``[start, end)``, sorted
    by ``(start, end, source, key)``. ``start`` and ``end`` are aware.

    ``sources`` names the sources to read (``None``: every applicable one; ``"events"`` is
    this module's own). Plugin sources are called for the public view with no viewer, and
    for a signed-in ``viewer`` only with ``source_viewer`` (who they are asked for); without
    it every plugin pair of a signed-in read is skipped (``no_viewer`` in ``sources`` of the
    answer), which fails safe."""
    who = viewer if viewer is not None else ResourcePrincipal(user_id=None, permissions=frozenset())
    filters = OccurrenceFilters(
        calendar_ids=_set(calendar_ids),
        category_ids=_set(category_ids),
        types=_set(types),
        sources=_set(sources),
        locale=locale,
        include_unpublished=viewer is not None,
    )
    with tenant_scope(tenant_id):
        return await _read.occurrences(
            session,
            tenant_id=tenant_id,
            viewer=who,
            start=start,
            end=end,
            filters=filters,
            default_locale=default_locale,
            source_viewer=source_viewer,
        )
