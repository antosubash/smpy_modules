"""Inertia view endpoints for the AI module."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from inertia import InertiaResponse
from simple_module_hosting.inertia_deps import InertiaDep
from simple_module_hosting.permissions import RequiresPermission

from sm_ai import constants

router = APIRouter()


@router.get(
    "/",
    response_model=None,
    dependencies=[Depends(RequiresPermission(constants.PERM_MANAGE))],
)
async def settings_page(inertia: InertiaDep) -> InertiaResponse:
    # Settings are fetched client-side from /api/ai/settings so a save can
    # refresh without a full Inertia round trip. The page name is inlined as a
    # literal (SM003/SM004 static-AST pairing); a unit test asserts it matches
    # constants._PAGE_SETTINGS.
    return await inertia.render("Ai/Settings")
