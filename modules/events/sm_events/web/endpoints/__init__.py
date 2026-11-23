"""The admin JSON API, mounted under ``ROUTE_PREFIX_API``."""

from __future__ import annotations

from fastapi import APIRouter, Depends

from sm_events.core.tenancy import bind_admin


def build_api_router() -> APIRouter:
    """Every admin API router in one; ``module.register_routes`` wraps it in the
    CSRF check. A new API router is added here, nowhere else.

    The tenant binding is this router's **first** dependency, and FastAPI puts a
    parent router's dependencies ahead of every included route's, so it is first
    for every route below. Not cosmetic: yield dependencies exit in reverse, and
    ``get_db`` - opened by the permission check - commits on its way out, which
    has to happen while the tenant is still bound."""
    from sm_events.web.endpoints import (
        calendars_api,
        categories_api,
        events_actions_api,
        events_api,
        extensions_api,
        feed_tokens_api,
        imports_api,
        occurrences_api,
        registrations_api,
        reminders_api,
        shares_api,
        subscriptions_api,
    )

    router = APIRouter(dependencies=[Depends(bind_admin)])
    for sub in (
        calendars_api.router,
        extensions_api.router,
        feed_tokens_api.router,
        imports_api.router,
        categories_api.router,
        shares_api.router,
        events_api.router,
        events_actions_api.router,
        registrations_api.router,
        occurrences_api.router,
        reminders_api.router,
        subscriptions_api.router,
    ):
        router.include_router(sub)
    return router
