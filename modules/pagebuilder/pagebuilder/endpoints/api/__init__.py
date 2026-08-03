"""JSON admin API for the pagebuilder module, split by resource.

Mounted by ``PagebuilderModule.register_routes`` under ``/api/pagebuilder``.
Sub-routers carry no prefix of their own, so every path is identical to the
single-file version this replaced.
"""

from __future__ import annotations

from fastapi import APIRouter

from pagebuilder.endpoints.api import layout, pages, revisions, uploads, workflow

router = APIRouter()
router.include_router(pages.router)
router.include_router(workflow.router)
router.include_router(revisions.router)
router.include_router(layout.router)
router.include_router(uploads.router)

__all__ = ["router"]
