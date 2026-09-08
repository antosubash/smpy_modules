"""Inertia view routes for the pagebuilder module.

Admin views are mounted under the module's ``view_prefix`` (``/pagebuilder``).
The public viewer is mounted at the host root via ``register_routes`` so the
URL is ``/{public_route_prefix}/{slug}`` (default ``/p/{slug}``) rather than
namespaced under the admin prefix.
"""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query
from inertia import InertiaResponse
from simple_module_db import get_db
from simple_module_hosting.inertia_deps import InertiaDep
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import board as board_query
from pagebuilder import locales
from pagebuilder.contracts.schemas import (
    LayoutDetail,
    LayoutRevisionListResponse,
    LayoutRevisionRead,
    MediaAssetListResponse,
    PageListResponse,
    PageRead,
    PageRevisionListResponse,
    PageRevisionRead,
    StatusFilter,
)
from pagebuilder.deps import get_media_service, get_settings
from pagebuilder.endpoints import content_views
from pagebuilder.layout_service import LayoutService, public_layout_props
from pagebuilder.media_service import MediaService
from pagebuilder.service import PagesService
from pagebuilder.settings import PagebuilderSettings

router = APIRouter()
# The content-snapshot screens live in their own module (300-line cap) but
# belong to this same router, so their URLs and dependencies are unchanged.
router.include_router(content_views.router)

_PAGE_LIST = "PageBuilder/PageList"
_VIEW_BOARD = "board"
_VIEW_LIST = "list"
_PAGE_TRASH = "PageBuilder/Trash"
_PAGE_EDITOR = "PageBuilder/PageEditor"
_PAGE_MEDIA = "PageBuilder/MediaLibrary"
_PAGE_MEDIA_DETAIL = "PageBuilder/MediaDetail"
_PAGE_PENDING = "PageBuilder/PendingReview"
_PAGE_LAYOUT_EDITOR = "PageBuilder/LayoutEditor"
# The draft preview deliberately reuses the public component — see admin_preview.
_PAGE_PUBLIC = "PageBuilder/PublicPage"


PAGE_LIST_LIMIT = 25


@router.get("/", response_model=None)
async def admin_list(
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
    search: str = "",
    status_filter: Annotated[StatusFilter, Query(alias="status")] = None,
    locale_filter: Annotated[str, Query(alias="locale")] = "",
    offset: int = Query(default=0, ge=0),
    view: str = Query(default=_VIEW_BOARD),
) -> InertiaResponse:
    """Page list, filtered server-side.

    The filter lives in the query string rather than in component state so a
    filtered list is a URL: it survives a reload, it can be linked to, and the
    browser's back button steps through the filters the way a user expects it
    to.
    """
    # An unconfigured tag filters nothing rather than 404ing: the value comes
    # off a query string, and a link to a language the site has since dropped
    # should show the list, not an error.
    locale = locales.resolve(locale_filter)
    pages, total = await PagesService(db).list_pages(
        search=search,
        status=status_filter,
        locale=locale,
        limit=PAGE_LIST_LIMIT,
        offset=offset,
    )
    # Deleting the last row of the last page leaves the offset past the end.
    # Re-ask for the final page rather than rendering an empty table under a
    # pager that says there are results.
    if not pages and total:
        offset = max(0, ((total - 1) // PAGE_LIST_LIMIT) * PAGE_LIST_LIMIT)
        pages, total = await PagesService(db).list_pages(
            search=search,
            status=status_filter,
            locale=locale,
            limit=PAGE_LIST_LIMIT,
            offset=offset,
        )
    payload = PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=total)

    # The board is the default view. The table stays a click away rather than
    # being replaced: it is the only view that can sort, page and filter by an
    # exact status, and those are real jobs the columns cannot do.
    board: list[dict] | None = None
    if view != _VIEW_LIST:
        board = board_query.to_payload(
            await board_query.load(db, search=search, locale=locale),
            lambda item: PageRead.model_validate(item).model_dump(mode="json"),
        )

    return await inertia.render(
        _PAGE_LIST,
        {
            "pages": payload.model_dump(mode="json"),
            "board": board,
            "filters": {
                "search": search,
                "status": status_filter.value if status_filter else "",
                "locale": locale or "",
                "offset": offset,
                "limit": PAGE_LIST_LIMIT,
                "view": _VIEW_LIST if view == _VIEW_LIST else _VIEW_BOARD,
            },
            **_locale_props(),
        },
    )


def _locale_props() -> dict:
    """The site's content languages, for every screen that offers a choice.

    Server-rendered rather than fetched so the language column and the New
    page dialog paint with the first response instead of flashing a
    single-language list and then correcting itself.
    """
    return {
        "locales": list(locales.supported()),
        "default_locale": locales.default(),
    }


@router.get("/trash", response_model=None)
async def admin_trash(inertia: InertiaDep) -> InertiaResponse:
    """Pages waiting out the retention window.

    Fetched client-side: restore and purge both change the list under the
    cursor, and an Inertia round trip per row would discard the scroll position
    every time.
    """
    return await inertia.render(_PAGE_TRASH)


@router.get("/pending", response_model=None)
async def admin_pending(
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
) -> InertiaResponse:
    """Approver queue view — pages awaiting review."""
    pages = await PagesService(db).list_pending()
    payload = PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=len(pages))
    return await inertia.render(
        _PAGE_PENDING,
        {"pages": payload.model_dump(mode="json"), **_locale_props()},
    )


@router.get("/new", response_model=None)
async def admin_new(inertia: InertiaDep) -> InertiaResponse:
    return await inertia.render(
        _PAGE_EDITOR, {"page": None, "revisions": [], **_locale_props()}
    )


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
            "page": (await service.detail(page)).model_dump(mode="json"),
            "revisions": revisions_payload.model_dump(mode="json")["items"],
            **_locale_props(),
        },
    )


@router.get("/{page_id}/preview", response_model=None)
async def admin_preview(
    page_id: int,
    inertia: InertiaDep,
    db: AsyncSession = Depends(get_db),
    settings: PagebuilderSettings = Depends(get_settings),
) -> InertiaResponse:
    """The draft as a visitor would see it.

    Rendered through the *public* page component rather than a preview-only
    one: a preview built from a second renderer is a preview that can disagree
    with the published page, which makes it worse than no preview at all.

    It reads ``draft_data``, so it answers the question the published URL
    cannot — what the unsaved-to-live version looks like. This is an admin
    route and stays behind the session, and it is marked noindex whatever the
    page's own setting says, because a preview URL that gets indexed in place
    of the real one is the one failure here that would be hard to undo.
    """
    page = await PagesService(db).get_page(page_id)
    layout = await LayoutService(db).get()
    return await inertia.render(
        _PAGE_PUBLIC,
        {
            "title": page.title,
            "data": page.draft_data or {},
            "meta_description": page.meta_description,
            "og_image": page.og_image,
            "canonical_url": None,
            "og_url": None,
            "index_in_search": False,
            "json_ld": page.json_ld,
            "site_name": settings.site_name,
            "twitter_handle": settings.twitter_handle,
            # No alternates: a preview is one draft, and advertising the
            # published translations of it from behind the session would name
            # live URLs on a page that is deliberately noindex.
            "locale": page.locale,
            **public_layout_props(layout),
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


@router.get("/media/{asset_id}", response_model=None)
async def admin_media_detail(asset_id: int, inertia: InertiaDep) -> InertiaResponse:
    """One asset: what it shows, who credited it, and which pages depend on it.

    Only the id is rendered. The asset and its usage list are fetched
    client-side because editing the alt text has to re-check the usage — the
    two travel together, and a full Inertia round trip per keystroke would not.
    """
    return await inertia.render(_PAGE_MEDIA_DETAIL, {"asset_id": asset_id})
