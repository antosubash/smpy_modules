"""The admin JSON API, mounted under ``ROUTE_PREFIX_API``."""

from __future__ import annotations

from fastapi import APIRouter


def build_api_router() -> APIRouter:
    """Every admin API router in one; ``module.register_routes`` wraps it in the
    CSRF check. A new API router is added here, nowhere else."""
    from sm_newsletter.web.endpoints import campaigns_api, cards_api, preview_api, settings_api

    router = APIRouter()
    for sub in (settings_api.router, campaigns_api.router, cards_api.router, preview_api.router):
        router.include_router(sub)
    return router
