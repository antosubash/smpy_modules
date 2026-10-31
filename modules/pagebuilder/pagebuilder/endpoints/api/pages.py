"""Page CRUD and listing endpoints."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from pagebuilder import locales
from pagebuilder.contracts.schemas import (
    LocalesResponse,
    PageCreate,
    PageDetail,
    PageListResponse,
    PageRead,
    PageTranslationCreate,
    PageUpdate,
    StatusFilter,
)
from pagebuilder.endpoints.api._deps import require_approve, require_edit
from pagebuilder.service import PagesService

router = APIRouter()


@router.get("/pages", response_model=PageListResponse)
async def list_pages(
    db: AsyncSession = Depends(get_db),
    search: str | None = None,
    status_filter: Annotated[StatusFilter, Query(alias="status")] = None,
    locale: str | None = Query(
        default=None,
        description="Only pages authored in this language. Unset lists every "
        "language, which is what an unfiltered admin list wants.",
    ),
    # Unbounded by default, deliberately: a seed reads this endpoint to build a
    # slug-to-id map, and a default page size would make it recreate pages it
    # already has. Callers that page ask for it.
    limit: int | None = Query(default=None, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
) -> PageListResponse:
    pages, total = await PagesService(db).list_pages(
        search=search,
        status=status_filter,
        locale=locales.resolve(locale),
        limit=limit,
        offset=offset,
    )
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=total)


@router.get("/pages/trash", response_model=PageListResponse, dependencies=[require_edit])
async def list_trash(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    """Pages waiting out the retention window.

    Declared above "/pages/{page_id}" with the other literal paths, or "trash"
    is parsed as a page id and answers 422.
    """
    pages = await PagesService(db).list_trash()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=len(pages))


@router.get("/pages/templates", response_model=PageListResponse)
async def list_templates(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    """Starting points offered by the New page dialog.

    Declared with the other literal paths, above "/pages/{page_id}", or
    "templates" is parsed as a page id and answers 422.
    """
    pages = await PagesService(db).list_templates()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=len(pages))


# Declared before "/pages/{page_id}" so the literal path wins the match.
# Keep these two adjacent — separating them across modules would make the
# ordering depend on router include order instead of being visible here.
@router.get(
    "/pages/pending",
    response_model=PageListResponse,
    dependencies=[require_approve],
)
async def list_pending(db: AsyncSession = Depends(get_db)) -> PageListResponse:
    """Approver queue — pages currently in ``submitted_for_review``."""
    pages = await PagesService(db).list_pending()
    return PageListResponse(items=[PageRead.model_validate(p) for p in pages], total=len(pages))


@router.get("/locales", response_model=LocalesResponse)
async def list_locales() -> LocalesResponse:
    """Which languages a page may be authored in.

    Served rather than compiled into the frontend so the language switcher and
    the New page dialog offer exactly what the deployment configured — a
    hardcoded list would show a language the API then refuses.
    """
    return LocalesResponse(locales=list(locales.supported()), default=locales.default())


@router.post(
    "/pages",
    response_model=PageDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_edit],
)
async def create_page(data: PageCreate, db: AsyncSession = Depends(get_db)) -> PageDetail:
    service = PagesService(db)
    return await service.detail(await service.create(data))


@router.get("/pages/{page_id}", response_model=PageDetail)
async def get_page(page_id: int, db: AsyncSession = Depends(get_db)) -> PageDetail:
    service = PagesService(db)
    return await service.detail(await service.get_page(page_id))


@router.post(
    "/pages/{page_id}/translations",
    response_model=PageDetail,
    status_code=status.HTTP_201_CREATED,
    dependencies=[require_edit],
)
async def create_translation(
    page_id: int,
    data: PageTranslationCreate,
    db: AsyncSession = Depends(get_db),
) -> PageDetail:
    """Start this page's counterpart in another language.

    Returns the *new* page, not the source: the caller's next move is to open
    the editor on it, and making them re-read the source to find its id would
    be a round trip for something this response already knows.
    """
    service = PagesService(db)
    return await service.detail(await service.create_translation(page_id, data))


@router.put(
    "/pages/{page_id}",
    response_model=PageDetail,
    dependencies=[require_edit],
)
async def update_page(
    page_id: int,
    data: PageUpdate,
    db: AsyncSession = Depends(get_db),
) -> PageDetail:
    service = PagesService(db)
    return await service.detail(await service.update(page_id, data))


@router.post(
    "/pages/{page_id}/restore",
    response_model=PageDetail,
    dependencies=[require_edit],
)
async def restore_page(page_id: int, db: AsyncSession = Depends(get_db)) -> PageDetail:
    """Bring a page back out of the trash. It returns as a draft."""
    service = PagesService(db)
    return await service.detail(await service.restore(page_id))


@router.delete(
    "/pages/{page_id}/purge",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_edit],
)
async def purge_page(
    page_id: int, request: Request, db: AsyncSession = Depends(get_db)
) -> None:
    """Remove a trashed page for good. Not reversible.

    Carries the bus for the same reason the soft delete no longer does: this is
    the point at which other modules must drop what they keyed to the page.
    """
    bus = getattr(request.app.state.sm, "event_bus", None)
    await PagesService(db, event_bus=bus).purge(page_id)


@router.delete(
    "/pages/{page_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    dependencies=[require_edit],
)
async def delete_page(page_id: int, db: AsyncSession = Depends(get_db)) -> None:
    """Move the page to trash. Reversible until the retention sweep runs.

    Deliberately publishes nothing: `PageDeleted` is what tells other modules to
    drop their own rows, and a restore would then bring the page back stripped
    of everything keyed to it. That event belongs to purge.
    """
    await PagesService(db).delete(page_id)
