"""One event's page (``/{slug}``), registered after every fixed path.

Order in the handler, each step answering before the next can leak: tenant (none is the module 404
with no query) → slug lookup in this language (else a renamed slug's 301, to a public target only,
else the 404) → ``?date=`` (a series' occurrence; anything else is the 404) → the page's data →
``ETag``/304 → render → head, language → cache headers. The 404 is the same for a slug that never
existed, a draft, an internal or private calendar's event, a trashed row, another tenant's and a
text in another language.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request, Response
from simple_module_db.deps import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from sm_events.content.public_read import event_by_slug, resolve_event_redirect
from sm_events.core import constants
from sm_events.core.settings import EventsSettings
from sm_events.web.endpoints.deps import get_settings
from sm_events.web.endpoints.public import _cache, _clock, _head, _urls
from sm_events.web.endpoints.public._errors import PublicErrorRoute
from sm_events.web.endpoints.public._event_context import load_context, validator_parts
from sm_events.web.endpoints.public._event_props import build_props, description_for_head
from sm_events.web.endpoints.public._not_found import not_found
from sm_events.web.endpoints.public._occurrence import (
    ShownOccurrence,
    next_occurrences,
    parse_date_param,
    shown_occurrence,
)
from sm_events.web.endpoints.public._respond import conditional
from sm_events.web.endpoints.public._tenant import public_tenant

__all__ = ["event_router"]

_METHODS = sorted(constants.PUBLIC_METHODS)


def event_router(locale: str) -> APIRouter:
    router = APIRouter(route_class=PublicErrorRoute)

    @router.api_route("/{slug}", methods=_METHODS, response_model=None)
    async def event_page(
        slug: str,
        request: Request,
        inertia: InertiaDep,
        date: str | None = Query(None),
        db: AsyncSession = Depends(get_db),
        tenant: str | None = Depends(public_tenant),
        settings: EventsSettings = Depends(get_settings),
    ) -> Response:
        async def missing() -> Response:
            return await not_found(request, inertia, db, locale=locale, tenant=tenant)

        if tenant is None:
            return await not_found(request, inertia, db, locale=locale, tenant=None)
        found = await event_by_slug(db, locale, slug)
        if found is None:
            moved = await resolve_event_redirect(db, locale, slug)
            if moved is None:
                return await missing()
            target = _urls.event_path(moved, locale)
            if request.url.query:
                target = f"{target}?{request.url.query}"
            return _cache.permanent_redirect(request, settings, target)
        event, text = found
        day = parse_date_param(date)
        if day == "invalid" or (day is not None and not event.rrule):
            return await missing()
        shown: ShownOccurrence | None = None
        if day is not None:
            shown = await shown_occurrence(db, event, day)  # type: ignore[arg-type]
            if shown is None:  # skipped, or not an instance
                return await missing()
        ctx = await load_context(db, event, text, locale)
        if ctx is None:
            return await missing()
        upcoming = (
            next_occurrences(
                event, ctx.overrides, now=_clock.now(), limit=constants.NEXT_OCCURRENCES
            )
            if event.rrule and shown is None
            else []
        )
        variant = "inertia" if request.headers.get("x-inertia") else "html"
        etag = _cache.page_etag(
            *validator_parts(ctx, shown, upcoming),
            variant=variant,
            viewer=_cache.viewer_key(request),
        )
        if (unchanged := conditional(request, settings, kind="page", etag=etag)) is not None:
            return unchanged
        props = build_props(ctx, shown, upcoming, lambda path: _urls.absolute(request, path))
        response = await inertia.render(constants._PAGE_PUBLIC_EVENT, props.model_dump(mode="json"))
        head = _head.event_head(
            title=text.seo_title or text.title,
            description=description_for_head(ctx),
            canonical=props.canonical_url,
            image=props.image,
            index_in_search=props.index_in_search,
            json_ld=props.json_ld,
            locale=locale,
            alternates=[a.model_dump() for a in props.alternates],
            nonce=getattr(request.state, "csp_nonce", None),
        )
        response = _head.inject(_head.set_html_lang(response, locale), head)
        response.headers["Content-Language"] = locale
        return _cache.apply(response, request, settings, kind="page", etag=etag)

    return router
