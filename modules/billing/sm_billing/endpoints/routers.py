"""Router wiring, kept out of ``module.py`` so the hooks stay one line."""

from __future__ import annotations

from fastapi import APIRouter


def include(api_router: APIRouter, view_router: APIRouter) -> None:
    """Mount the tenant API, admin API, webhook and tenant views."""
    from sm_billing.endpoints.webhooks import router as webhooks

    # No CSRF on the webhook: Stripe has no session, the signature is the auth.
    view_router.include_router(webhooks)


def include_admin(admin_router: APIRouter) -> None:
    """Mount the platform-admin Inertia views under ``/admin/billing``."""
