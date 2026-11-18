"""The ``.ics`` routes: every public calendar's feed, one calendar's, one event's.

Machine-read: a request that resolved no tenant is a plain 404 with the ``{"detail", "code"}``
envelope. Everything in a file comes from the public gate through
:mod:`sm_events.feeds.select`, and the file is built by ``icalendar`` alone.

* ``/calendar.ics``: every public calendar, the window and caps of Ruling 25.
* ``/c/{calendar}.ics``: one public calendar. A renamed calendar's old slug 301s to the new
  file (a subscription survives), only to a calendar that is public now.
* ``/{slug}.ics``: one event, with its whole series and every override, no window. An old
  slug 301s the same way. It needs a text in this language, as the page does.

A truncated feed says so in ``X-Events-Truncated: 1`` and logs once. ``HEAD`` answers the
headers of ``GET`` with no body. The ``ETag`` is a digest of the body and is evaluated only
after the row passed the gate.
"""

from __future__ import annotations

import logging
import re
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.content import calendar_redirects
from sm_events.content.public_read import calendar_by_slug, event_by_slug, resolve_event_redirect
from sm_events.core import constants, locales, timezones
from sm_events.core.errors import NotFound
from sm_events.core.settings import EventsSettings
from sm_events.feeds import ics_calendar
from sm_events.feeds.ics_event import FeedEvent
from sm_events.feeds.select import feed_events, single_event
from sm_events.web.endpoints.deps import get_settings
from sm_events.web.endpoints.public import _cache, _clock, _urls
from sm_events.web.endpoints.public._errors import PublicErrorRoute
from sm_events.web.endpoints.public._respond import machine_response

__all__ = ["calendar_feed_router", "event_feed_router", "safe_filename"]

_log = logging.getLogger("sm_events.public")
_METHODS = sorted(constants.PUBLIC_METHODS)
_UNSAFE = re.compile(r"[^A-Za-z0-9._-]")
TRUNCATED_HEADER = "X-Events-Truncated"


def safe_filename(slug: str) -> str:
    """An ASCII-only, quote-free file name stem."""
    return _UNSAFE.sub("-", slug) or constants.EVENT_SLUG_FALLBACK


def _zone_range(now: datetime) -> tuple[datetime, datetime]:
    """Whole calendar years around ``now``, so the ``VTIMEZONE`` (and with it the body and
    its ``ETag``) does not change from one day to the next."""
    return (
        datetime(now.year - 1, 1, 1, tzinfo=UTC),
        datetime(now.year + constants.FEED_YEARS_AHEAD, 12, 31, tzinfo=UTC),
    )


def _respond(
    request: Request,
    settings: EventsSettings,
    body: bytes,
    *,
    truncated: bool = False,
    filename: str | None = None,
) -> Response:
    headers: dict[str, str] = {}
    if filename is not None:
        headers["Content-Disposition"] = f'attachment; filename="{safe_filename(filename)}.ics"'
    if truncated:
        headers[TRUNCATED_HEADER] = "1"
        _log.info("events: a public feed was cut at its caps (%s)", request.url.path)
    return machine_response(
        request, settings, body, media_type=constants.ICS_MEDIA_TYPE, kind="feed", headers=headers
    )


def _file(items: list[FeedEvent], *, name: str, timezone: str, now: datetime) -> bytes:
    first, last = _zone_range(now)
    return ics_calendar.build(items, name=name, timezone=timezone, first=first, last=last)


def calendar_feed_router(locale: str) -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route(f"/{constants.SEGMENT_CALENDAR_FEED}.ics", methods=_METHODS)
    async def all_calendars_feed(
        request: Request,
        db: AsyncSession = Depends(get_db),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        now = _clock.now()
        read = await feed_events(
            db,
            calendar_id=None,
            locale=locale,
            default_locale=locales.default(),
            now=now,
            url_for=lambda slug, loc: _urls.absolute(request, _urls.event_path(slug, loc)),
        )
        body = _file(
            read.items,
            name=constants.MODULE_NAME,
            timezone=timezones.effective(settings.default_timezone),
            now=now,
        )
        return _respond(request, settings, body, truncated=read.truncated)

    @router.api_route(f"/{constants.SEGMENT_CALENDAR}/{{calendar}}.ics", methods=_METHODS)
    async def calendar_feed(
        calendar: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        found = await calendar_by_slug(db, calendar)
        if found is None:
            moved = await calendar_redirects.resolve(db, calendar)
            if moved is None:
                raise NotFound
            return _cache.permanent_redirect(
                request, settings, _urls.calendar_ics_path(moved, locale)
            )
        now = _clock.now()
        read = await feed_events(
            db,
            calendar_id=found.id,
            locale=locale,
            default_locale=locales.default(),
            now=now,
            url_for=lambda slug, loc: _urls.absolute(request, _urls.event_path(slug, loc)),
        )
        body = _file(
            read.items,
            name=found.name,
            timezone=timezones.effective(found.default_timezone),
            now=now,
        )
        return _respond(request, settings, body, truncated=read.truncated)

    return router


def event_feed_router(locale: str) -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route("/{slug}.ics", methods=_METHODS)
    async def event_ics(
        slug: str,
        request: Request,
        db: AsyncSession = Depends(get_db),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        found = await event_by_slug(db, locale, slug)
        if found is None:
            moved = await resolve_event_redirect(db, locale, slug)
            if moved is None:
                raise NotFound
            return _cache.permanent_redirect(request, settings, _urls.event_ics_path(moved, locale))
        event, text = found
        item = await single_event(
            db,
            event,
            locale=locale,
            default_locale=locales.default(),
            url_for=lambda s, loc: _urls.absolute(request, _urls.event_path(s, loc)),
        )
        now = _clock.now()
        body = _file(
            [item],
            name=text.title,
            timezone=timezones.effective(event.timezone),
            now=now,
        )
        return _respond(request, settings, body, filename=text.slug)

    return router
