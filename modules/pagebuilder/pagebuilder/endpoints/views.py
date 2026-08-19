"""Inertia view routes for the pagebuilder module.

Admin views are mounted under the module's ``view_prefix`` (``/pagebuilder``).
The public viewer is mounted at the host root via ``register_routes`` so the
URL is ``/{public_route_prefix}/{slug}`` (default ``/p/{slug}``) rather than
namespaced under the admin prefix.
"""

from __future__ import annotations

import hashlib
from datetime import datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from inertia import InertiaResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder.contracts.schemas import (
    LayoutDetail,
    LayoutRevisionListResponse,
    LayoutRevisionRead,
    MediaAssetListResponse,
    PageDetail,
    PageListResponse,
    PageRead,
    PageRevisionListResponse,
    PageRevisionRead,
    StatusFilter,
)
from pagebuilder import board as board_query
from pagebuilder.deps import get_media_service, get_settings
from pagebuilder.layout_service import LayoutService, public_layout_props
from pagebuilder.media_service import MediaService
from pagebuilder.service import PagesService
from pagebuilder.settings import PagebuilderSettings


def _etag_for(
    page_id: int,
    updated_at: datetime | None,
    layout_updated_at: datetime | None = None,
) -> str:
    """Stable, short ETag derived from page identity + last-modified time.

    ``layout_updated_at`` participates so a site-wide header / footer
    edit invalidates every page's cached chrome — without it, clients
    keep serving stale layout from cache until the page itself changes.
    """
    stamp = updated_at.isoformat() if updated_at is not None else ""
    layout_stamp = (
        layout_updated_at.isoformat() if layout_updated_at is not None else ""
    )
    digest = hashlib.sha1(f"{page_id}:{stamp}:{layout_stamp}".encode()).hexdigest()[:16]
    return f'W/"{digest}"'


def _public_base_url(request: Request, settings: PagebuilderSettings) -> str:
    """Resolve the public origin used to build absolute URLs.

    Prefer the explicit setting (the deployment knows its public host)
    and only fall back to the inbound request for local dev / scenarios
    where the host header is trustworthy. Always returned without a
    trailing slash so callers can concatenate path segments directly.
    """
    if settings.public_base_url:
        return settings.public_base_url.rstrip("/")
    return f"{request.url.scheme}://{request.url.netloc}".rstrip("/")


def _absolute_page_url(
    request: Request, settings: PagebuilderSettings, slug: str
) -> str:
    base = _public_base_url(request, settings)
    prefix = settings.public_route_prefix.rstrip("/")
    return f"{base}{prefix}/{slug}"


router = APIRouter()
public_router = APIRouter()

_PAGE_LIST = "PageBuilder/PageList"
_VIEW_BOARD = "board"
_VIEW_LIST = "list"
_PAGE_EDITOR = "PageBuilder/PageEditor"
_PAGE_PUBLIC = "PageBuilder/PublicPage"
_PAGE_MEDIA = "PageBuilder/MediaLibrary"
_PAGE_PENDING = "PageBuilder/PendingReview"
_PAGE_LAYOUT_EDITOR = "PageBuilder/LayoutEditor"


PAGE_LIST_LIMIT = 25


@router.get("/", response_model=None)
async def admin_list(
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
    search: str = "",
    status_filter: Annotated[StatusFilter, Query(alias="status")] = None,
    offset: int = Query(default=0, ge=0),
    view: str = Query(default=_VIEW_BOARD),
) -> InertiaResponse:
    """Page list, filtered server-side.

    The filter lives in the query string rather than in component state so a
    filtered list is a URL: it survives a reload, it can be linked to, and the
    browser's back button steps through the filters the way a user expects it
    to.
    """
    pages, total = await PagesService(db).list_pages(
        search=search, status=status_filter, limit=PAGE_LIST_LIMIT, offset=offset
    )
    # Deleting the last row of the last page leaves the offset past the end.
    # Re-ask for the final page rather than rendering an empty table under a
    # pager that says there are results.
    if not pages and total:
        offset = max(0, ((total - 1) // PAGE_LIST_LIMIT) * PAGE_LIST_LIMIT)
        pages, total = await PagesService(db).list_pages(
            search=search, status=status_filter, limit=PAGE_LIST_LIMIT, offset=offset
        )
    payload = PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=total)

    # The board is the default view. The table stays a click away rather than
    # being replaced: it is the only view that can sort, page and filter by an
    # exact status, and those are real jobs the columns cannot do.
    board: list[dict] | None = None
    if view != _VIEW_LIST:
        stages = await board_query.load(db, search=search)
        board = [
            {
                "key": stage.key,
                "label": stage.label,
                "total": stage.total,
                "items": [
                    PageRead.model_validate(item).model_dump(mode="json")
                    for item in stage.items
                ],
            }
            for stage in stages
            # An empty review column would advertise a workflow this site may
            # not use; a non-empty one must never be hidden, or its pages are
            # stranded with no route to them.
            if stage.key != board_query.IN_REVIEW or stage.total
        ]

    return await inertia.render(
        _PAGE_LIST,
        {
            "pages": payload.model_dump(mode="json"),
            "board": board,
            "filters": {
                "search": search,
                "status": status_filter.value if status_filter else "",
                "offset": offset,
                "limit": PAGE_LIST_LIMIT,
                "view": _VIEW_LIST if view == _VIEW_LIST else _VIEW_BOARD,
            },
        },
    )


@router.get("/pending", response_model=None)
async def admin_pending(
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
) -> InertiaResponse:
    """Approver queue view — pages awaiting review."""
    pages = await PagesService(db).list_pending()
    payload = PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=len(pages))
    return await inertia.render(
        _PAGE_PENDING, {"pages": payload.model_dump(mode="json")}
    )


@router.get("/new", response_model=None)
async def admin_new(inertia: InertiaDep) -> InertiaResponse:
    return await inertia.render(_PAGE_EDITOR, {"page": None, "revisions": []})


@router.get("/{page_id}/edit", response_model=None)
async def admin_edit(
    page_id: int,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
) -> InertiaResponse:
    service = PagesService(db)
    page = await service.get_page(page_id)
    revisions = await service.list_revisions(page_id)
    revisions_payload = PageRevisionListResponse(
        items=[PageRevisionRead.model_validate(r) for r in revisions]
    )
    return await inertia.render(
        _PAGE_EDITOR,
        {
            "page": PageDetail.model_validate(page).model_dump(mode="json"),
            "revisions": revisions_payload.model_dump(mode="json")["items"],
        },
    )


@router.get("/layout", response_model=None)
async def admin_layout(
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
) -> InertiaResponse:
    """Edit the site-wide header + footer."""
    service = LayoutService(db)
    layout = await service.get()
    revisions = await service.list_revisions()
    return await inertia.render(
        _PAGE_LAYOUT_EDITOR,
        {
            "layout": LayoutDetail.model_validate(layout).model_dump(mode="json"),
            "revisions": LayoutRevisionListResponse(
                items=[LayoutRevisionRead.model_validate(r) for r in revisions]
            ).model_dump(mode="json")["items"],
        },
    )


@router.get("/media", response_model=None)
async def admin_media(
    inertia: InertiaDep,
    media: MediaService = Depends(get_media_service),
) -> InertiaResponse:
    # Server-render the first page only; the React side handles further
    # pagination + filtering via the JSON API. Folder list is loaded so
    # the sidebar paints immediately on first navigation.
    assets, next_cursor = await media.list_assets()
    folders = await media.list_folders()
    payload = MediaAssetListResponse(
        items=[media.to_read(a) for a in assets],
        next_cursor=next_cursor,
        folders=folders,
    )
    return await inertia.render(
        _PAGE_MEDIA,
        {
            "initial": payload.model_dump(mode="json"),
        },
    )


@public_router.get("/{slug}", response_model=None)
async def public_view(
    slug: str,
    request: Request,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
    settings: PagebuilderSettings = Depends(get_settings),
) -> Response:
    page = await PagesService(db).get_by_slug_published(slug)
    if page is None or page.published_data is None:
        raise HTTPException(status_code=404, detail="Page not found")

    layout = await LayoutService(db).get()
    etag = _etag_for(page.id or 0, page.updated_at, layout.updated_at)
    cache_parts = [f"max-age={settings.public_cache_max_age}"]
    if settings.public_cache_swr > 0:
        cache_parts.append(f"stale-while-revalidate={settings.public_cache_swr}")
    cache_control = "public, " + ", ".join(cache_parts)

    def apply_headers(response: Response) -> Response:
        response.headers["ETag"] = etag
        response.headers["Cache-Control"] = cache_control
        if settings.public_csp:
            response.headers["Content-Security-Policy"] = settings.public_csp
        return response

    if request.headers.get("if-none-match") == etag:
        return apply_headers(Response(status_code=304))

    canonical = page.canonical_url or _absolute_page_url(request, settings, slug)
    return apply_headers(
        await inertia.render(
            _PAGE_PUBLIC,
            {
                "title": page.title,
                "data": page.published_data,
                "meta_description": page.meta_description,
                "og_image": page.og_image,
                "canonical_url": canonical,
                "og_url": canonical,
                "index_in_search": page.index_in_search,
                "json_ld": page.json_ld,
                "site_name": settings.site_name,
                "twitter_handle": settings.twitter_handle,
                **public_layout_props(layout),
            },
        )
    )
