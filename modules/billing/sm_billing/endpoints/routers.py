"""Router wiring, kept out of ``module.py`` so the hooks stay one line."""

from __future__ import annotations

from fastapi import APIRouter


def include(api_router: APIRouter, view_router: APIRouter) -> None:
    """Mount the tenant API, admin API, webhook and tenant views."""
    from sm_billing.endpoints.admin_api import router as admin_api
    from sm_billing.endpoints.api import router as api
    from sm_billing.endpoints.views import router as views
    from sm_billing.endpoints.webhooks import router as webhooks

    api_router.include_router(admin_api)
    api_router.include_router(api)
    # No CSRF on the webhook: Stripe has no session, the signature is the auth.
    view_router.include_router(webhooks)
    view_router.include_router(views)


def include_admin(admin_router: APIRouter) -> None:
    """Mount the platform-admin Inertia views under ``/admin/billing``."""
    from sm_billing.endpoints.admin_views import router as admin_views

    admin_router.include_router(admin_views)
