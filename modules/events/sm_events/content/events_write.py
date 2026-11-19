"""Create and update events. No FastAPI, no commit: the request finishes the
transaction (:func:`sm_events.content.bus.commit`) and so publishes what a write
queued.

* **Rights.** Creating needs ``write_events`` on the calendar (404 when the calendar
  is not visible, 403 when it is but not writable). Changing an event needs the same
  on its calendar, plus ``events.publish`` when the event is published or scheduled
  (:func:`sm_events.core.access.events.require`).
* **The stale guard comes first.** Every write opens a savepoint and its first
  statement is the compare-and-set on ``revision``; any failure after it rolls the
  savepoint back, so a refused write leaves no revision bump and no history row,
  and the request's transaction is never aborted.
* **Recurrence and sub-events exclude each other**, and neither the calendar nor
  the parent can change after create.
"""

from __future__ import annotations

import uuid
from typing import Any

from simple_module_core.resources import ResourcePrincipal

from sm_events.content._core import apply_patch, create_core
from sm_events.content.guard import Unchanged
from sm_events.core.access.events import load_event, require
from sm_events.core.access.rights import writable_calendar
from sm_events.core.errors import ImageOffSite
from sm_events.core.web_urls import is_site_image
from sm_events.models import Event
from sm_events.web.schemas.events_in import EventCreate, EventPatch

__all__ = ["create_event", "update_event"]


def _check_image(image: str | None, stored: str | None, origin: str | None) -> None:
    """A NEW image must be one the site's pages may load. A value equal to the stored one is
    accepted (stored data stays as it is), and ``origin=None`` (the importer, a worker) skips the
    check: it has no site to compare with."""
    if origin is None or not image or image == stored:
        return
    if not is_site_image(image, origin):
        raise ImageOffSite


async def create_event(
    db: Any,
    who: ResourcePrincipal,
    data: EventCreate,
    *,
    locales: tuple[str, ...],
    viewer: Any = None,
    site_origin: str | None = None,
) -> Event:
    """A new draft at revision 1, with its texts and a ``created`` history row."""
    _check_image(data.image, None, site_origin)
    calendar = await writable_calendar(db, who, data.calendar_id)
    return await create_core(db, calendar, data, actor=who.user_id, locales=locales, viewer=viewer)


async def update_event(
    db: Any,
    who: ResourcePrincipal,
    event_id: uuid.UUID,
    data: EventPatch,
    *,
    locales: tuple[str, ...],
    viewer: Any = None,
    site_origin: str | None = None,
) -> Event:
    """Apply a PATCH: only the fields the body set. One that changes nothing (only
    ``expected_revision``, or values equal to the stored ones) writes nothing: same
    revision, no history row, no bus event, and the unchanged event comes back."""
    event, rights = await load_event(db, who, event_id)
    require(rights)
    if "image" in data.model_fields_set:
        _check_image(data.image, event.image, site_origin)
    try:
        await apply_patch(db, who.user_id, event, data, locales, viewer=viewer)
    except Unchanged:
        await db.refresh(event)  # the savepoint rolled back: the stored revision
    return event
