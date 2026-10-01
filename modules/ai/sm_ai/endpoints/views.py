"""Inertia view endpoints for the AI module."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission
from simple_module_inertia import InertiaResponse

from sm_ai import constants

router = APIRouter()


@router.get(
    "/",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_MANAGE))],
)
async def settings_page(inertia: InertiaDep) -> InertiaResponse:
    # Settings are fetched client-side from /api/ai/settings so a save can
    # refresh without a full Inertia round trip.
    #
    # The page name comes from the constant, matching news and this repo's
    # check_hardcoded_strings. The framework's own modules inline the literal
    # instead, for the SM003/SM004 static-AST pairing — the two conventions
    # disagree, and an in-repo module follows the in-repo linter.
    return await inertia.render(constants._PAGE_SETTINGS)
