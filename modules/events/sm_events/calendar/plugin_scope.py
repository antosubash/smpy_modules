"""Which ``(calendar, source)`` pairs a read calls.

Only calendars the viewer can see (the access policy's own filter, so an anonymous read
sees public calendars only), only sources enabled on them, and:

* **anonymous**: only ``public`` sources, with no viewer; an entry whose source is not
  installed, or not public, is not even mentioned;
* **signed in**: every enabled source, with the caller's :class:`SourceViewer`. A caller
  that gives none (another module going through the contract without one) gets every
  pair ``skipped`` with code ``no_viewer``: failing safe, since a source narrows by who
  is asking;
* a type filter without the default type excludes every plugin source (its items are of the
  default type), and a category filter excludes every plugin source (their items have no category);
* ``filters.sources`` narrows to the named sources; a calendar id the viewer cannot see
  is dropped silently, so existence cannot be probed.

Pairs are ordered by calendar name, then source id.
"""

from __future__ import annotations

from typing import Any

from simple_module_core.resources import ResourcePrincipal
from sqlmodel import col

from sm_events.calendar import registry, source_entries
from sm_events.calendar.extension_types import SourceStatus, SourceViewer
from sm_events.calendar.occurrence import OccurrenceFilters
from sm_events.calendar.plugin_runner import SKIPPED, Call
from sm_events.core import constants
from sm_events.core.access import visible_calendars
from sm_events.models import Calendar

__all__ = ["CODE_NO_VIEWER", "plugin_calls"]

CODE_NO_VIEWER = "no_viewer"


def _wanted(filters: OccurrenceFilters) -> frozenset[str] | None:
    """The plugin sources the filter names, or ``None`` for every one."""
    if filters.sources is None:
        return None
    return filters.sources - {constants.SOURCE_EVENTS}


async def plugin_calls(
    db: Any,
    viewer: ResourcePrincipal,
    source_viewer: SourceViewer | None,
    filters: OccurrenceFilters,
) -> tuple[list[Call], list[SourceStatus]]:
    """The calls to make, and the statuses of the pairs that are not made at all."""
    wanted = _wanted(filters)
    if wanted is not None and not wanted:
        return [], []  # only the built-in source was asked for
    if filters.types is not None and constants.BUILTIN_TYPE not in filters.types:
        return [], []  # a plugin's item is of the default type: a narrower type filter drops it
    if filters.category_ids is not None:
        return [], []  # a filter narrows: a plugin's item has no category
    stmt = visible_calendars(viewer)
    if filters.calendar_ids is not None:
        stmt = stmt.where(col(Calendar.id).in_(filters.calendar_ids))
    stmt = stmt.order_by(col(Calendar.name), col(Calendar.id)).limit(constants.CALENDARS_MAX)
    anonymous = viewer.user_id is None
    calls: list[Call] = []
    skipped: list[SourceStatus] = []
    for cal in (await db.execute(stmt)).scalars().all():
        for entry in sorted(source_entries.read(cal.sources), key=lambda e: e.id):
            if wanted is not None and entry.id not in wanted:
                continue
            source = registry.get_source(entry.id)
            if anonymous and (source is None or not source.public):
                continue
            if source is not None and not anonymous and source_viewer is None:
                skipped.append(
                    SourceStatus(
                        id=entry.id, calendar_id=cal.id, status=SKIPPED, code=CODE_NO_VIEWER
                    )  # type: ignore[arg-type]
                )
                continue
            calls.append(Call(source_entries.source_calendar(cal), entry, source))
    return calls, skipped
