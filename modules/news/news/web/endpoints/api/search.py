"""Cross-section admin search.

Deliberately *not* under ``/api/news/articles`` or ``/api/news/categories``:
those prefixes are registered as anonymously readable so the public feed block
works, and this endpoint reaches across drafts, unpublished pages and the media
library.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query, Request
from simple_module_db import get_db
from simple_module_hosting.permissions import ensure_resolved_permissions
from sqlalchemy.ext.asyncio import AsyncSession

from news.contracts.schemas import SearchResults
from news.integrations import pagebuilder
from news.web.endpoints.api._deps import require_edit
from news.web.services import search_service

router = APIRouter(dependencies=[require_edit])


@router.get("/search", response_model=SearchResults)
async def search(
    request: Request,
    q: str = Query("", description="Free text. Empty returns nothing, not everything."),
    per_section: int = Query(search_service.PER_SECTION, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> SearchResults:
    # Pages and media only for a caller pagebuilder itself would show them to.
    held = await ensure_resolved_permissions(request)
    return await search_service.search(
        db, q, include_pagebuilder=pagebuilder.may_read(held), per_section=per_section
    )
