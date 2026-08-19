"""News REST API, assembled from one module per resource.

Split by resource rather than kept in one file so each stays inside the repo's
300-line cap and the draft-visibility rule has a single home in ``_deps``.
"""

from __future__ import annotations

from fastapi import APIRouter

from news.endpoints.api.articles import router as articles_router
from news.endpoints.api.categories import router as categories_router
from news.endpoints.api.tags import router as tags_router

router = APIRouter()
router.include_router(articles_router)
router.include_router(categories_router)
router.include_router(tags_router)

__all__ = ["router"]
