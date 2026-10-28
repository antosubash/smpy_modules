"""Inertia screens of the Images module, mounted under ``VIEW_PREFIX``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_images.deps import require_view
from sm_images.tenancy import bind_admin

# ``bind_admin`` first, for the reason ``endpoints.api``'s router gives.
router = APIRouter(dependencies=[Depends(bind_admin), require_view])
