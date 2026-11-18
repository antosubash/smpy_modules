"""``/sitemap.xml``: every public, indexable event, on the default language's prefix only.

One sitemap for the whole site, listing every language at its own address (a crawler wants one
document telling it what exists). It holds the index of each language, each public calendar's page
in each language, then every publicly visible event text that has a slug and is not ``noindex``,
newest first, at most ``SITEMAP_MAX_URLS`` addresses in all. ``?date=`` addresses are never listed:
an occurrence is the same document as its series.

Everything comes from the gate (``public_events()``, ``public_calendars()``), so a draft, an event
of an internal or private calendar, a trashed row and another tenant's never appears. The XML is
built with ``ElementTree``, which escapes every value. Machine-read: a request that resolved no
tenant is the plain 404. Neither pagebuilder nor news has a registry for another module's sitemap
(each serves its own), so this one is advertised the same way: at its own address, for the
operator's ``robots.txt``.
"""

from __future__ import annotations

from datetime import date
from typing import Any
from xml.etree import ElementTree as ET

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db
from sqlalchemy import func
from sqlalchemy.ext.asyncio import AsyncSession
from sqlmodel import col

from sm_events.core import constants, locales
from sm_events.core.access.public import public_calendars, public_events
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.models import Calendar, Event, EventText
from sm_events.web.endpoints.deps import get_settings
from sm_events.web.endpoints.public import _urls
from sm_events.web.endpoints.public._errors import PublicErrorRoute
from sm_events.web.endpoints.public._respond import machine_response

__all__ = ["sitemap_router", "sitemap_urls"]

Entry = tuple[str, date | None]


async def sitemap_urls(db: Any, *, absolute: Any) -> list[Entry]:
    """``(absolute URL, lastmod)`` for the whole site, at most ``SITEMAP_MAX_URLS``."""
    served = locales.supported()
    entries: list[Entry] = [(absolute(_urls.index_path(loc)), None) for loc in served]
    stmt = public_calendars().order_by(col(Calendar.name)).limit(constants.CALENDARS_MAX)
    for calendar in (await db.execute(stmt)).scalars():
        modified = (calendar.updated_at or calendar.created_at).date()
        entries += [(absolute(_urls.calendar_path(calendar.slug, loc)), modified) for loc in served]
    room = constants.SITEMAP_MAX_URLS - len(entries)
    if room <= 0:
        return entries[: constants.SITEMAP_MAX_URLS]
    stamp = func.coalesce(Event.updated_at, Event.created_at)
    rows = await db.execute(
        public_events()
        .join(EventText, col(EventText.event_id) == col(Event.id))
        .where(
            EventText.tenant_id == bound_tenant(),  # type: ignore[arg-type]
            col(EventText.noindex).is_(False),
            col(EventText.locale).in_(served),
        )
        .with_only_columns(EventText.slug, EventText.locale, Event.updated_at, Event.created_at)
        .order_by(stamp.desc(), col(EventText.id))
        .limit(room)
    )
    for slug, locale, updated, created in rows.all():
        entries.append((absolute(_urls.event_path(slug, locale)), (updated or created).date()))
    return entries


def _xml(entries: list[Entry]) -> bytes:
    root = ET.Element("urlset", xmlns=constants.SITEMAP_NAMESPACE)
    for loc, lastmod in entries:
        node = ET.SubElement(root, "url")
        ET.SubElement(node, "loc").text = loc
        if lastmod is not None:
            ET.SubElement(node, "lastmod").text = lastmod.isoformat()
    return ET.tostring(root, encoding="utf-8", xml_declaration=True)


def sitemap_router() -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route(f"/{constants.SEGMENT_SITEMAP}.xml", methods=sorted(constants.PUBLIC_METHODS))
    async def sitemap(
        request: Request,
        db: AsyncSession = Depends(get_db),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        entries = await sitemap_urls(db, absolute=lambda path: _urls.absolute(request, path))
        return machine_response(
            request, settings, _xml(entries), media_type=constants.XML_MEDIA_TYPE, kind="sitemap"
        )

    return router
