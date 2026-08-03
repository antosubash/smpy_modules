"""Inertia view endpoints for News."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from inertia import InertiaResponse
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission

from news import constants

router = APIRouter()


@router.get(
    "/",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_VIEW))],
)
async def article_list(inertia: InertiaDep) -> InertiaResponse:
    # The list is fetched client-side from /api/news/articles so inline edits
    # can refresh a row without a full Inertia round trip. The page name is
    # inlined as a literal (rather than constants._PAGE_LIST) so the
    # SM003/SM004 static-AST diagnostics can pair this call with
    # pages/NewsList.tsx; a unit test asserts the literal matches the constant.
    return await inertia.render("News/NewsList")
