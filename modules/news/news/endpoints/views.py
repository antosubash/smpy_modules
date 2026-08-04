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
    # The list is fetched client-side from /api/news/articles so an inline edit
    # can refresh one row without a full Inertia round trip.
    #
    # The page name comes from the constant, matching pagebuilder and this
    # repo's check_hardcoded_strings. The framework's own modules inline the
    # literal instead, for the SM003/SM004 static-AST pairing — the two
    # conventions disagree, and an in-repo module follows the in-repo linter.
    return await inertia.render(constants._PAGE_LIST)
