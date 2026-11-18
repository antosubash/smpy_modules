"""The upcoming list and one public calendar's page (``/`` and ``/c/{calendar}``).

Both are one screen, ``Events/PublicIndex``: the list server-rendered (crawlable, no JavaScript
needed) with a ``?view=calendar`` tab for the read-only grid. A request that resolved no tenant is
the module 404 without a query. Query parameters are validated, with one answer for bad input: an
unknown, hidden or malformed ``?category=`` and a page past the end are the 404, ``?page=`` and
``?view=`` junk is page 1 and the list.
"""

from __future__ import annotations

import hashlib
from typing import Any
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_db.deps import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from sm_events.content import calendar_redirects
from sm_events.content.public_read import calendar_by_slug, category_by_slug, public_categories
from sm_events.core import constants, locales
from sm_events.core.access.public import public_calendars
from sm_events.core.settings import EventsSettings
from sm_events.core.timezones import effective
from sm_events.models import Calendar, Category
from sm_events.web.endpoints.deps import get_settings
from sm_events.web.endpoints.public import _cache, _clock, _head, _urls
from sm_events.web.endpoints.public._errors import PublicErrorRoute
from sm_events.web.endpoints.public._listing import (
    category_name,
    month_groups,
    page_count,
    page_param,
    upcoming,
)
from sm_events.web.endpoints.public._not_found import not_found
from sm_events.web.endpoints.public._respond import conditional
from sm_events.web.endpoints.public._tenant import public_tenant
from sm_events.web.schemas.public import (
    AlternateOut,
    PublicCalendarOut,
    PublicCategoryOut,
    PublicIndexProps,
)

__all__ = ["index_router"]

_METHODS = sorted(constants.PUBLIC_METHODS)
VIEW_CALENDAR = "calendar"
VIEW_LIST = "list"


def _calendar_out(cal: Calendar, request_locale: str) -> PublicCalendarOut:
    return PublicCalendarOut(
        id=str(cal.id),
        slug=cal.slug,
        name=cal.name,
        color=cal.color,
        description=cal.description,
        default_timezone=effective(cal.default_timezone),
        url=_urls.calendar_path(cal.slug, request_locale),
        feed_url=_urls.calendar_ics_path(cal.slug, request_locale),
    )


def _category_out(cat: Category, locale: str) -> PublicCategoryOut:
    return PublicCategoryOut(
        id=str(cat.id),
        slug=cat.slug,
        name=category_name(cat, locale, locales.default()),
        color=cat.color,
    )


def _path(locale: str, calendar: Calendar | None) -> str:
    return _urls.calendar_path(calendar.slug, locale) if calendar else _urls.index_path(locale)


def _query(category: Category | None, page: int) -> str:
    pairs = [("category", category.slug)] if category else []
    if page > 1:
        pairs.append(("page", str(page)))
    return f"?{urlencode(pairs)}" if pairs else ""


async def _render(
    request: Request,
    inertia: Any,
    db: Any,
    settings: EventsSettings,
    *,
    locale: str,
    calendar: Calendar | None,
    category_slug: str | None,
    page_raw: str | None,
    view_raw: str | None,
) -> Response:
    category: Category | None = None
    if category_slug:
        category = await category_by_slug(db, category_slug)
        if category is None:  # unknown, hidden and malformed alike
            return await not_found(request, inertia, db, locale=locale, tenant=_bound())
    page = page_param(page_raw)
    items = await upcoming(
        db,
        locale=locale,
        default_locale=locales.default(),
        now=_clock.now(),
        calendar_ids=[calendar.id] if calendar else None,
        category_id=category.id if category else None,
    )
    pages = page_count(len(items))
    if page > pages:
        return await not_found(request, inertia, db, locale=locale, tenant=_bound())
    calendars = (await db.execute(public_calendars().order_by(col(Calendar.name)))).scalars()
    props = PublicIndexProps(
        locale=locale,
        title=calendar.name if calendar else _urls.site_title(settings),
        page=page,
        page_count=pages,
        groups=month_groups(items, page),
        calendars=[_calendar_out(c, locale) for c in calendars],
        calendar=_calendar_out(calendar, locale) if calendar else None,
        categories=[_category_out(c, locale) for c in await public_categories(db)],
        category=category.slug if category else None,
        view=VIEW_CALENDAR if view_raw == VIEW_CALENDAR else VIEW_LIST,
        feed_url=_urls.calendar_ics_path(calendar.slug if calendar else None, locale),
        default_timezone=effective(
            calendar.default_timezone if calendar else settings.default_timezone
        ),
        api_url=_urls.api_path(),
        alternates=_alternates(request, calendar),
    )
    body = props.model_dump(mode="json")
    digest = hashlib.sha256(props.model_dump_json().encode()).hexdigest()
    variant = "inertia" if request.headers.get("x-inertia") else "html"
    etag = _cache.page_etag(digest, variant=variant, viewer=_cache.viewer_key(request))
    if (unchanged := conditional(request, settings, kind="listing", etag=etag)) is not None:
        return unchanged
    response = await inertia.render(constants._PAGE_PUBLIC_INDEX, body)
    canonical = _urls.absolute(request, _path(locale, calendar) + _query(category, page))
    head = _head.listing_head(
        title=props.title,
        description=calendar.description if calendar else None,
        canonical=canonical,
        feed_url=_urls.absolute(request, props.feed_url),
        locale=locale,
        alternates=[a.model_dump() for a in props.alternates],
    )
    response = _head.inject(_head.set_html_lang(response, locale), head)
    response.headers["Content-Language"] = locale
    return _cache.apply(response, request, settings, kind="listing", etag=etag)


def _alternates(request: Request, calendar: Calendar | None) -> list[AlternateOut]:
    """``hreflang`` for each content language, plus ``x-default``; none for a single language."""
    languages = locales.supported()
    if len(languages) < 2:
        return []
    out = [
        AlternateOut(locale=loc, url=_urls.absolute(request, _path(loc, calendar)))
        for loc in languages
    ]
    default = _urls.absolute(request, _path(locales.default(), calendar))
    return [*out, AlternateOut(locale="x-default", url=default)]


def _bound() -> str:
    from sm_events.core.tenancy import bound_tenant

    return bound_tenant()


def index_router(locale: str) -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route(
        f"/{constants.SEGMENT_CALENDAR}/{{calendar}}", methods=_METHODS, response_model=None
    )
    async def calendar_page(
        calendar: str,
        request: Request,
        inertia: InertiaDep,
        category: str | None = Query(None),
        page: str | None = Query(None),
        view: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
        tenant: str | None = Depends(public_tenant),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        if tenant is None:
            return await not_found(request, inertia, db, locale=locale, tenant=None)
        found = await calendar_by_slug(db, calendar)
        if found is None:
            moved = await calendar_redirects.resolve(db, calendar)
            if moved is None:
                return await not_found(request, inertia, db, locale=locale, tenant=tenant)
            target = _urls.calendar_path(moved, locale)
            if request.url.query:
                target = f"{target}?{request.url.query}"
            return _cache.permanent_redirect(request, settings, target)
        return await _render(
            request, inertia, db, settings,
            locale=locale, calendar=found, category_slug=category, page_raw=page, view_raw=view,
        )  # fmt: skip

    @router.api_route("/", methods=_METHODS, response_model=None)
    async def index_page(
        request: Request,
        inertia: InertiaDep,
        category: str | None = Query(None),
        page: str | None = Query(None),
        view: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
        tenant: str | None = Depends(public_tenant),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        if tenant is None:
            return await not_found(request, inertia, db, locale=locale, tenant=None)
        return await _render(
            request, inertia, db, settings,
            locale=locale, calendar=None, category_slug=category, page_raw=page, view_raw=view,
        )  # fmt: skip

    return router
