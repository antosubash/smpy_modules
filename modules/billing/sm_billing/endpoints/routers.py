"""Router wiring, kept out of ``module.py`` so the hooks stay one line."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_billing.live import follow_live_settings

#: Every billing route first catches up with a provider switch saved on
#: another worker, so none of them writes through a provider the database no
#: longer names (#85).
_LIVE = [Depends(follow_live_settings)]


def include(api_router: APIRouter, view_router: APIRouter) -> None:
    """Mount the tenant API, admin API, webhook and tenant views."""
    from sm_billing.endpoints.admin_api import router as admin_api
    from sm_billing.endpoints.admin_usage_api import router as admin_usage_api
    from sm_billing.endpoints.api import router as api
    from sm_billing.endpoints.views import router as views
    from sm_billing.endpoints.webhooks import router as webhooks

    api_router.include_router(admin_api, dependencies=_LIVE)
    api_router.include_router(admin_usage_api, dependencies=_LIVE)
    api_router.include_router(api, dependencies=_LIVE)
    # No CSRF on the webhook: Stripe has no session, the signature is the auth.
    view_router.include_router(webhooks, dependencies=_LIVE)
    view_router.include_router(views, dependencies=_LIVE)


def include_admin(admin_router: APIRouter) -> None:
    """Mount the platform-admin Inertia views under ``/admin/billing``."""
    from sm_billing.endpoints.admin_views import router as admin_views

    admin_router.include_router(admin_views, dependencies=_LIVE)
