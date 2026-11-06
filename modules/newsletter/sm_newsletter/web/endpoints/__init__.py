"""The admin JSON API, mounted under ``ROUTE_PREFIX_API``."""

from __future__ import annotations

from fastapi import APIRouter


def build_api_router() -> APIRouter:
    """Every admin API router in one; ``module.register_routes`` wraps it in the
    CSRF check. A new API router is added here, nowhere else."""
    from sm_newsletter.web.endpoints import (
        audience_api,
        campaigns_api,
        cards_api,
        imports_api,
        lists_api,
        outbox_api,
        preview_api,
        report_api,
        segments_api,
        sending_api,
        settings_api,
        subscribers_api,
        suppressions_api,
        test_send_api,
    )

    router = APIRouter()
    for sub in (
        settings_api.router,
        campaigns_api.router,
        cards_api.router,
        imports_api.router,
        lists_api.router,
        outbox_api.router,
        preview_api.router,
        report_api.router,
        segments_api.router,
        audience_api.router,
        sending_api.router,
        subscribers_api.router,
        suppressions_api.router,
        test_send_api.router,
    ):
        router.include_router(sub)
    return router
