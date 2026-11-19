"""``/api/events/public/*``: the three anonymous routes the pagebuilder blocks read.

A block on a pagebuilder page cannot learn events' configurable public prefix, so these live at a
fixed path (``constants.PUBLIC_BLOCKS_API``), like images' ``/api/images/public/stats``. Each is a
thin wrapper over what the public pages already use, so they see exactly what an anonymous visitor
sees: the same gate (``public_calendars``, ``public_events``), the machine binder (no tenant, a
404), :class:`~sm_events.web.endpoints.public._errors.PublicApiRoute` (a bad query is the module's
JSON envelope), and the ``api`` cache policy with a body ``ETag``.

* ``/calendars``: the public calendars a block may choose, or those of the slugs it names, and the
  categories a public event uses.
* ``/upcoming``: the next public occurrences (at most ``count``).
* ``/occurrences``: PR 4's ``/api/occurrences``, parameters (calendar *ids*) and answer.

**Calendars and the category are slugs, resolved on every request** (a renamed calendar keeps
working through its redirects). No ``calendar``: every public calendar. A selection that resolves to
nothing is *nothing*, never a fallback to all, and a category that is not a public one matches
nothing too. A calendar that stopped being public is dropped without a trace: no error, no name.
Nothing here carries an event's id.
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from typing import Any

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from sm_events.content.public_read import category_by_slug, public_categories, valid_slug
from sm_events.core import constants, locales
from sm_events.core.access.public import public_calendars
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bind_public, bound_tenant
from sm_events.core.timezones import effective
from sm_events.models import Calendar, CalendarRedirect
from sm_events.web.endpoints.deps import get_settings
from sm_events.web.endpoints.public import _clock
from sm_events.web.endpoints.public._api import occurrences_response
from sm_events.web.endpoints.public._errors import PublicApiRoute
from sm_events.web.endpoints.public._listing import category_name, upcoming
from sm_events.web.endpoints.public._respond import machine_response
from sm_events.web.schemas.public import (
    BlockCalendarOut,
    BlockCalendarsOut,
    BlockQuery,
    PublicCategoryOut,
    PublicOccurrenceParams,
    UpcomingOut,
    block_query,
)

__all__ = ["blocks_router", "resolve_calendars"]

_METHODS = sorted(constants.PUBLIC_METHODS)


async def resolve_calendars(db: Any, slugs: Sequence[str]) -> list[Calendar]:
    """The public calendars named by ``slugs``, in that order: a current slug, else an old one
    through the calendar redirects (a slug's holder wins over a redirect on it). A slug that is
    malformed, unknown, not public or trashed is dropped, with no trace."""
    wanted = [s for s in dict.fromkeys(slugs) if valid_slug(s)]
    if not wanted:
        return []
    current = {
        c.slug: c
        for c in (await db.execute(public_calendars().where(col(Calendar.slug).in_(wanted))))
        .scalars()
        .all()
    }
    missing = [s for s in wanted if s not in current]
    moved: dict[str, Calendar] = {}
    if missing:
        stmt = (
            public_calendars()
            .join(CalendarRedirect, col(CalendarRedirect.calendar_id) == col(Calendar.id))
            .where(
                CalendarRedirect.tenant_id == bound_tenant(),  # type: ignore[arg-type]
                col(CalendarRedirect.old_slug).in_(missing),
            )
            .add_columns(col(CalendarRedirect.old_slug))
        )
        moved = {old: cal for cal, old in (await db.execute(stmt)).all()}
    chosen = [current.get(s) or moved.get(s) for s in wanted]
    unique: dict[uuid.UUID, Calendar] = {c.id: c for c in chosen if c is not None}
    return list(unique.values())


async def _selection(db: Any, slugs: tuple[str, ...]) -> list[Calendar] | None:
    """``None``: no selection (every public calendar). A list, possibly empty: what resolved."""
    return await resolve_calendars(db, slugs) if slugs else None


def _json(request: Request, settings: EventsSettings, model: Any) -> Response:
    return machine_response(
        request,
        settings,
        model.model_dump_json().encode(),
        media_type=constants.JSON_MEDIA_TYPE,
        kind="api",
    )


def _calendar_out(cal: Calendar) -> BlockCalendarOut:
    return BlockCalendarOut(
        id=str(cal.id),
        slug=cal.slug,
        name=cal.name,
        color=cal.color,
        default_timezone=effective(cal.default_timezone),
    )


def blocks_router() -> APIRouter:
    router = APIRouter(route_class=PublicApiRoute, dependencies=[Depends(bind_public)])

    @router.api_route("/calendars", methods=_METHODS)
    async def block_calendars(
        request: Request,
        query: BlockQuery = Depends(block_query),
        db: AsyncSession = Depends(get_db),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        chosen = await _selection(db, query.calendars)
        if chosen is None:
            stmt = public_calendars().order_by(col(Calendar.name)).limit(constants.CALENDARS_MAX)
            chosen = list((await db.execute(stmt)).scalars().all())
        default = locales.default()
        zone = (
            effective(chosen[0].default_timezone)
            if len(chosen) == 1
            else effective(settings.default_timezone)
        )
        body = BlockCalendarsOut(
            calendars=[_calendar_out(c) for c in chosen],
            categories=[
                PublicCategoryOut(
                    id=str(c.id),
                    slug=c.slug,
                    name=category_name(c, query.locale, default),
                    color=c.color,
                )
                for c in await public_categories(db)
            ],
            default_timezone=zone,
        )
        return _json(request, settings, body)

    @router.api_route("/upcoming", methods=_METHODS)
    async def block_upcoming(
        request: Request,
        query: BlockQuery = Depends(block_query),
        db: AsyncSession = Depends(get_db),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        chosen = await _selection(db, query.calendars)
        category = await category_by_slug(db, query.category) if query.category else None
        if (chosen is not None and not chosen) or (query.category and category is None):
            return _json(request, settings, UpcomingOut(items=[]))  # nothing, never "all"
        items = await upcoming(
            db,
            locale=query.locale,
            default_locale=locales.default(),
            now=_clock.now(),
            calendar_ids=None if chosen is None else [c.id for c in chosen],
            category_id=category.id if category else None,
            limit=query.count,
        )
        return _json(request, settings, UpcomingOut(items=items[: query.count]))

    @router.api_route("/occurrences", methods=_METHODS)
    async def block_occurrences(
        request: Request,
        query: PublicOccurrenceParams,
        db: AsyncSession = Depends(get_db),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        return await occurrences_response(request, query, db, settings)

    return router
