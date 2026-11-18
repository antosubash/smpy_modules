"""Writing one staged item through the normal write path (Ruling 28).

:func:`write_item` is the only place an import touches events, and it goes through PR 2's own
write functions (``create_core`` and ``apply_patch``, the bodies below the rights check), so
slugs, the sanitiser, the stale guard, the validators and the revision history are PR 2's,
unchanged. What is the import's own:

* **Rights are checked for every item.** The worker has no session or directory, so the
  importer's ``events.*`` permissions as of the launch (``EventImport.grants``) are the
  principal's; share, ownership and trash are read from the database fresh each time. A
  manager who lost the role *after* the launch is a known window, documented; one who lost the
  calendar is refused from the next item. An item the importer may not write is skipped
  ``forbidden``, a locked event without ``events.publish`` ``publish_required``.
* **No bus.** The session's bus (if any) is detached for the write: 5,000 imported events must
  not become 5,000 notifications. The import row records the counts.
* **Idempotent on UID.** A new item takes the file's UID; losing the race for it on the unique
  key is a skip (``duplicate_uid``), never an error. An update compares only what the file
  maps and writes nothing, no revision, when it is already so.
* **Drafts by default**; published only when asked **and** the importer may publish, and never
  for a ``CLASS:PRIVATE`` or ``CONFIDENTIAL`` event.
"""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Literal

from pydantic import ValidationError
from simple_module_core.resources import ResourcePrincipal
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from sm_events.calendar.slugs import is_slug_conflict
from sm_events.calendar.times import to_span
from sm_events.content import bus, texts
from sm_events.content.events_write import apply_patch, create_core
from sm_events.content.guard import Unchanged
from sm_events.core import constants
from sm_events.core.access.events import event_rights, require
from sm_events.core.access.rights import writable_calendar
from sm_events.core.errors import EventsError, Forbidden, NotFound, PublishRequired, Stale
from sm_events.feeds.importing import policy
from sm_events.feeds.importing.model import MappedEvent, MappedOverride
from sm_events.models import Event, EventImport, EventImportItem, OccurrenceOverride
from sm_events.models.enums import EventStatus
from sm_events.models.event import UID_CONSTRAINT
from sm_events.web.schemas.events_in import EventCreate, EventPatch
from sm_events.web.schemas.texts import TextIn

__all__ = ["Written", "write_item"]


class PrivateKept(Exception):  # noqa: N818 - a verdict, not an error
    """A private item meets a published or scheduled event (see :mod:`.policy`)."""


Outcome = Literal["created", "updated", "unchanged", "skipped"]


@dataclass(frozen=True)
class Written:
    outcome: Outcome
    code: str | None = None
    event_id: uuid.UUID | None = None


def _skip(code: str | None) -> Written:
    return Written("skipped", code or "write_failed")


@asynccontextmanager
async def _muted(db: Any) -> AsyncIterator[None]:
    """The session without its bus for the block (put back after)."""
    held = db.info.pop(bus.BUS_KEY, None)
    try:
        yield
    finally:
        if held is not None:
            db.info[bus.BUS_KEY] = held


def _principal(imp: EventImport) -> ResourcePrincipal:
    return ResourcePrincipal(user_id=imp.created_by, permissions=frozenset(imp.grants or ()))


async def _calendar(db: Any, imp: EventImport) -> Any:
    """The calendar if the importer may still write events in it; otherwise ``Forbidden`` (a
    calendar that is gone or no longer visible is the same refusal, for the worker's purposes)."""
    try:
        return await writable_calendar(db, _principal(imp), imp.calendar_id)
    except NotFound:
        raise Forbidden from None


def _span(event_tz: str, all_day: bool, override: MappedOverride):
    return to_span(
        all_day=all_day,
        timezone=event_tz,
        start=override.start or "",
        end=override.end or "",
        recurring=True,
        fields=("start", "end"),
    )


def _wanted(event: Event, overrides: list[MappedOverride]) -> dict[datetime, tuple]:
    out: dict[datetime, tuple] = {}
    for item in overrides:
        span = _span(event.timezone, event.all_day, item) if item.kind == "moved" else None
        out[item.original_start.astimezone(UTC)] = (
            item.kind,
            span.starts_at if span else None,
            span.ends_at if span else None,
        )
    return out


async def _replace_overrides(db: Any, event: Event, overrides: list[MappedOverride]) -> bool:
    """Make the event's overrides exactly the file's; whether anything changed."""
    held = list(
        (
            await db.execute(
                select(OccurrenceOverride).where(OccurrenceOverride.event_id == event.id)
            )
        ).scalars()
    )
    wanted = _wanted(event, overrides) if event.rrule else {}
    have = {r.original_start.astimezone(UTC): (r.kind, r.starts_at, r.ends_at) for r in held}
    if have == wanted:
        return False
    for row in held:
        await db.delete(row)
    await db.flush()
    for original, (kind, start, end) in wanted.items():
        db.add(
            OccurrenceOverride(
                event_id=event.id, original_start=original, kind=kind, starts_at=start, ends_at=end
            )
        )
    await db.flush()
    return True


def _create_body(imp: EventImport, mapped: MappedEvent, locale: str) -> EventCreate:
    return EventCreate(
        calendar_id=imp.calendar_id,
        times=mapped.times,
        rrule=mapped.rrule,
        cancelled=mapped.cancelled,
        attendance_mode=mapped.attendance_mode,  # type: ignore[arg-type]
        venue_name=mapped.venue_name,
        online_url=mapped.online_url,
        latitude=mapped.latitude,
        longitude=mapped.longitude,
        category_id=mapped.category_id,
        texts={locale: TextIn(title=mapped.title, description=mapped.description)},
    )


async def _create(db: Any, imp: EventImport, mapped: MappedEvent, locales, now) -> Written:
    who = _principal(imp)
    calendar = await _calendar(db, imp)
    publish = policy.publish_new(
        private=mapped.private_class,
        requested=imp.publish,
        may_publish=who.has(constants.PERM_PUBLISH),
    )
    async with db.begin_nested():
        event = await create_core(
            db,
            calendar,
            _create_body(imp, mapped, locales[0]),
            actor=imp.created_by,
            locales=locales,
            uid=mapped.uid,
            status=EventStatus.PUBLISHED.value if publish else EventStatus.DRAFT.value,
            published_at=now if publish else None,
            note=f"import #{imp.id}",
            before_history=lambda ev: _replace_overrides(db, ev, mapped.overrides),
        )
    return Written("created", None, event.id)


async def _patch(db: Any, imp, item, mapped: MappedEvent, event: Event, locales) -> EventPatch:
    held = (await texts.texts_of(db, [event.id]))[event.id].get(locales[0])
    keep: dict[str, Any] = {}
    if held is not None:  # the file's title and description; the text's other fields stay
        keep = {
            "summary": held.summary,
            "seo_title": held.seo_title,
            "seo_description": held.seo_description,
            "noindex": held.noindex,
        }
    sent: dict[str, Any] = {
        "expected_revision": item.expected_revision,
        "times": mapped.times,
        "rrule": mapped.rrule,
        "cancelled": mapped.cancelled,
        "attendance_mode": mapped.attendance_mode,
        "venue_name": mapped.venue_name,
        "online_url": mapped.online_url,
        "latitude": mapped.latitude,
        "longitude": mapped.longitude,
        "texts": {locales[0]: TextIn(title=mapped.title, description=mapped.description, **keep)},
        "drop_orphaned_overrides": True,
    }
    if mapped.category_id is not None:  # the file's category only when it names a known one
        sent["category_id"] = mapped.category_id
    return EventPatch(**sent)


async def _update(db: Any, imp, item, mapped: MappedEvent, locales) -> Written:
    who = _principal(imp)
    await _calendar(db, imp)
    event = (
        await db.execute(
            select(Event).where(Event.id == item.existing_event_id)  # type: ignore[arg-type]
        )
    ).scalar_one_or_none()
    if event is None or event.calendar_id != imp.calendar_id:
        raise Stale
    if policy.update_refused(
        private=mapped.private_class, status=event.status, publish_at=event.publish_at
    ):
        raise PrivateKept
    require(await event_rights(db, who, event))
    patch = await _patch(db, imp, item, mapped, event, locales)
    try:
        await apply_patch(
            db,
            imp.created_by,
            event,
            patch,
            locales,
            note=f"import #{imp.id}",
            after=lambda ev: _replace_overrides(db, ev, mapped.overrides),
        )
    except Unchanged:
        await db.refresh(event)
        return Written("unchanged", None, event.id)
    return Written("updated", None, event.id)


async def write_item(
    db: Any, imp: EventImport, item: EventImportItem, *, locales: tuple[str, ...], now: datetime
) -> Written:
    """Write ``item`` (the caller opens the savepoint, the transaction and the lease). The
    outcome and, for a skip, its code; an exception the module does not know propagates."""
    if item.verdict == "skip" or not item.payload:
        return _skip(item.reason)
    mapped = MappedEvent.model_validate(item.payload)
    if not _principal(imp).has(constants.PERM_MANAGE):
        return _skip("forbidden")
    try:
        async with _muted(db):
            if item.verdict == "update":
                return await _update(db, imp, item, mapped, locales)
            return await _create(db, imp, mapped, locales, now)
    except PrivateKept:
        return _skip(policy.PRIVATE_KEPT)
    except PublishRequired as exc:
        return _skip(exc.code)
    except Forbidden:
        return _skip("forbidden")
    except (Stale, NotFound):  # edited or trashed since the preview
        return _skip("changed_since_preview")
    except EventsError as exc:
        return _skip(exc.code)
    except ValidationError:
        return _skip("invalid_event")
    except IntegrityError as exc:
        if is_slug_conflict(exc, UID_CONSTRAINT):
            return _skip("duplicate_uid")
        raise
