"""News REST API, assembled from one module per resource.

Split by resource rather than kept in one file so each stays inside the repo's
300-line cap, and so the draft-visibility rule and the publish gate each have a
single home in ``_deps``.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from news.endpoints.api.article_tags import router as article_tags_router
from news.endpoints.api.articles import router as articles_router
from news.endpoints.api.body import router as body_router
from news.endpoints.api.categories import router as categories_router
from news.endpoints.api.search import router as search_router
from news.endpoints.api.tags import router as tags_router
from news.endpoints.api.translations import router as translations_router
from news.endpoints.api.workflow import router as workflow_router
from news.tenancy import bind_admin

# One binding for every API route. Router-level, so it runs before each
# endpoint's ``get_db`` and its commit happens while the tenant is still bound.
# The anonymous reads in ``PUBLIC_READ_PREFIXES`` come through here too: in
# MULTI mode they run in the tenant the framework resolved (the subdomain), and
# with none they are refused like any other admin read.
router = APIRouter(dependencies=[Depends(bind_admin)])
router.include_router(articles_router)
router.include_router(article_tags_router)
router.include_router(body_router)
router.include_router(categories_router)
router.include_router(search_router)
router.include_router(tags_router)
router.include_router(translations_router)
router.include_router(workflow_router)

__all__ = ["router"]
