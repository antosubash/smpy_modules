"""Cross-section admin search.

Deliberately *not* under ``/api/news/articles`` or ``/api/news/categories``:
those prefixes are registered as anonymously readable so the public feed block
works, and this endpoint reaches across drafts, unpublished pages and the media
library.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, Query
from simple_module_db import get_db
from sqlalchemy.ext.asyncio import AsyncSession

from news import search_service
from news.contracts.schemas import SearchResults
from news.endpoints.api._deps import require_edit

router = APIRouter(dependencies=[require_edit])


@router.get("/search", response_model=SearchResults)
async def search(
    q: str = Query("", description="Free text. Empty returns nothing, not everything."),
    per_section: int = Query(search_service.PER_SECTION, ge=1, le=50),
    db: AsyncSession = Depends(get_db),
) -> SearchResults:
    return await search_service.search(db, q, per_section=per_section)
