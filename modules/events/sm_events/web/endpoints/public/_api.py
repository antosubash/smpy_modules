"""``/api/occurrences``: the public occurrences read for the read-only grid (Ruling 32).

Machine-read, on the default language's prefix only. The read is the occurrences read called with
the anonymous principal and ``include_unpublished=False``; its own bounds apply (366 days, 2,000
items, ``truncated``). Each item's ``url`` becomes its public address (:func:`public_page`),
``editable`` is false, ``event_status`` is ``published``, and the internal ids (``event_id``,
``original_start``) are null: the grid needs neither. A calendar or category id the public may not
see matches nothing, as an unknown one does.
"""

from __future__ import annotations

import uuid
from datetime import date, datetime
from typing import Any
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Request, Response
from simple_module_db.deps import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.calendar.occurrence import Occurrence, OccurrenceFilters, OccurrencePage
from sm_events.calendar.occurrences import occurrences
from sm_events.content.public_read import pick_text, public_texts
from sm_events.core import constants, locales
from sm_events.core.access.public import ANONYMOUS
from sm_events.core.settings import EventsSettings
from sm_events.core.tenancy import bound_tenant
from sm_events.web.endpoints.deps import get_settings
from sm_events.web.endpoints.public import _urls
from sm_events.web.endpoints.public._errors import PublicErrorRoute
from sm_events.web.endpoints.public._respond import machine_response
from sm_events.web.schemas.public import PublicOccurrenceParams

__all__ = ["api_router", "occurrence_day", "public_page"]


def occurrence_day(item: Occurrence) -> date | None:
    """The local date a series instance is addressed by (``?date=``): that of its original start in
    the event's timezone; ``None`` for a one-off."""
    if item.original_start is None:
        return None
    return item.original_start.astimezone(ZoneInfo(item.timezone)).date()


def _public(item: Occurrence, texts: dict[str, Any], locale: str) -> Occurrence | None:
    chosen = texts.get(item.event_id) if item.event_id else None
    if not chosen:  # no text to link to: not a page a visitor can open
        return None
    text = pick_text(chosen, locale, locales.default())
    return item.model_copy(
        update={
            "url": _urls.event_path(text.slug, text.locale, occurrence_day(item)),
            "title": text.title,
            "lang": text.locale,
            "editable": False,
            "event_status": "published",
            "event_id": None,
            "original_start": None,
        }
    )


async def public_page(
    db: Any,
    *,
    tenant: str,
    start: datetime,
    end: datetime,
    calendar_ids: frozenset[uuid.UUID] | None,
    category_ids: frozenset[uuid.UUID] | None,
    locale: str,
) -> OccurrencePage:
    """What an anonymous visitor may see in ``[start, end)``: the read plus one texts query."""
    page = await occurrences(
        db,
        tenant_id=tenant,
        viewer=ANONYMOUS,
        start=start,
        end=end,
        filters=OccurrenceFilters(
            calendar_ids=calendar_ids,
            category_ids=category_ids,
            locale=locale,
            include_unpublished=False,
        ),
        default_locale=locales.default(),
    )
    texts = await public_texts(db, {i.event_id for i in page.items if i.event_id})
    shown = [p for item in page.items if (p := _public(item, texts, locale)) is not None]
    return OccurrencePage(items=shown, truncated=page.truncated)


def api_router() -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route(
        f"/{constants.SEGMENT_API}/occurrences", methods=sorted(constants.PUBLIC_METHODS)
    )
    async def public_occurrences(
        request: Request,
        query: PublicOccurrenceParams,
        db: AsyncSession = Depends(get_db),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        page = await public_page(
            db,
            tenant=bound_tenant(),
            start=query.start,
            end=query.end,
            calendar_ids=query.calendar_ids,
            category_ids=query.category_ids,
            locale=query.locale,
        )
        return machine_response(
            request,
            settings,
            page.model_dump_json().encode(),
            media_type=constants.JSON_MEDIA_TYPE,
            kind="api",
        )

    return router
