"""Calendar reads and writes. No FastAPI, no commit: failures are
:class:`~sm_events.core.errors.EventsError`, and the request finishes the
transaction. A write that can lose a race on the slug index flushes inside a
savepoint, so the session stays usable after the 409."""

from __future__ import annotations

import uuid
from typing import Any

from simple_module_core.resources import ACTION_DELETE, ResourcePrincipal
from sqlalchemy.exc import IntegrityError
from sqlmodel import select

from sm_events.calendar.slugs import free_slug, slug_taken, slugify
from sm_events.core import constants, timezones
from sm_events.core.access import POLICY, visible_calendars
from sm_events.core.errors import Forbidden, NotFound, SlugTaken
from sm_events.models import Calendar, Visibility
from sm_events.models.calendar import CALENDAR_SLUG_CONSTRAINT
from sm_events.web.schemas.calendars import CalendarCreate, CalendarPatch

# ``slug_taken`` is looked up through this module so a test can pin the pre-check.
_slug_taken = slug_taken


async def _flush_slug(db: Any, row: Calendar | None = None) -> None:
    """Flush in a savepoint; a unique-index hit on the slug is a 409."""
    try:
        async with db.begin_nested():
            if row is not None:
                db.add(row)
            await db.flush()
    except IntegrityError as exc:
        text = str(exc.orig)
        if CALENDAR_SLUG_CONSTRAINT not in text and "slug" not in text:
            raise
        raise SlugTaken from exc


async def list_calendars(
    db: Any, who: ResourcePrincipal, *, trashed: bool = False
) -> list[Calendar]:
    """What *who* may see, by name. ``trashed`` lists only trashed calendars
    *who* may delete (their own, or any for ``events.manage``)."""
    if trashed:
        stmt = POLICY.filter(
            who,
            ACTION_DELETE,
            select(Calendar)
            .where(Calendar.is_deleted.is_(True))
            .execution_options(include_deleted=True),
        )
    else:
        stmt = visible_calendars(who)
    stmt = stmt.order_by(Calendar.name, Calendar.id).limit(constants.CALENDARS_MAX)
    return list((await db.execute(stmt)).scalars().all())


async def create_calendar(
    db: Any, who: ResourcePrincipal, data: CalendarCreate, *, default_tz: str
) -> Calendar:
    """Insert a calendar owned by *who*. An explicit slug that is taken is a
    409; one derived from the name gets a ``-2``, ``-3``... suffix instead."""
    if who.user_id is None:
        raise Forbidden("A signed-in user is required")
    if data.slug is not None and await _slug_taken(db, Calendar, data.slug):
        raise SlugTaken
    row = Calendar(
        slug=data.slug or await free_slug(db, Calendar, slugify(data.name)),
        name=data.name,
        color=data.color,
        description=data.description,
        visibility=data.visibility.value,
        owner_id=who.user_id,
        default_timezone=data.default_timezone or timezones.effective(default_tz),
    )
    await _flush_slug(db, row)
    return row


async def update_calendar(db: Any, cal: Calendar, data: CalendarPatch) -> Calendar:
    """Apply a PATCH: only the fields the body set."""
    fields = data.model_dump(exclude_unset=True)
    new_slug = fields.get("slug")
    if (
        new_slug is not None
        and new_slug != cal.slug
        and await _slug_taken(db, Calendar, new_slug, except_id=cal.id)
    ):
        raise SlugTaken
    for name, value in fields.items():
        setattr(cal, name, value)
    await _flush_slug(db)
    return cal


async def set_visibility(db: Any, cal: Calendar, visibility: Visibility) -> Calendar:
    cal.visibility = visibility.value
    await db.flush()
    return cal


async def set_owner(db: Any, cal: Calendar, owner_id: str) -> Calendar:
    cal.owner_id = owner_id
    await db.flush()
    return cal


async def trash_calendar(db: Any, cal: Calendar, who: ResourcePrincipal) -> None:
    """Soft delete. The slug stays reserved, so a restore never collides."""
    await db.delete(cal)
    await db.flush()


async def restore_calendar(db: Any, who: ResourcePrincipal, calendar_id: uuid.UUID) -> Calendar:
    """Bring a trashed calendar back. Absent, not trashed, or not *who*'s to
    restore (not the owner, not an ``events.manage`` holder): ``NotFound``. A
    trashed calendar is invisible to everyone else, share holders and viewers of
    a once-public calendar included, so a refusal must not confirm it exists."""
    trashed = (
        select(Calendar)
        .where(Calendar.id == calendar_id, Calendar.is_deleted.is_(True))
        .execution_options(include_deleted=True)
    )
    row = (await db.execute(POLICY.filter(who, ACTION_DELETE, trashed))).scalars().first()
    if row is None:
        raise NotFound(constants.NOT_FOUND_DETAIL)
    row.is_deleted = False
    row.deleted_at = None
    row.deleted_by = None
    await db.flush()
    return row
