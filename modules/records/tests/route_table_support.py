"""Every route the records module mounts, for the isolation matrix's
"every route has a case" check (``test_tenancy_isolation``). Split from
:mod:`tests.isolation_support` for the 300-line cap."""

from __future__ import annotations

from types import SimpleNamespace

from fastapi import APIRouter, FastAPI
from fastapi.routing import iter_route_contexts
from settings.module_registry import ModuleSettingsRegistry
from sm_records import boot, constants
from sm_records.module import RecordsModule
from sm_records.settings import RecordsSettings


def route_table() -> list[tuple[str, str]]:
    """``(method, path)`` for every route the module mounts, through the same
    hooks the host calls (``register_routes``, ``boot.mount_public_router``,
    ``boot.mount_submission_views``)."""
    module = RecordsModule()
    module.settings = RecordsSettings()
    app = FastAPI()
    app.state.settings = SimpleNamespace(module_registry=ModuleSettingsRegistry())
    module.register_settings(app)
    api_router = APIRouter(prefix=module.meta.route_prefix)
    view_router = APIRouter(prefix=module.meta.view_prefix)
    module.register_routes(api_router, view_router)
    app.include_router(api_router)
    app.include_router(view_router)
    boot.mount_public_router(app, module.settings)
    boot.mount_submission_views(app)
    prefixes = (
        module.meta.route_prefix,
        module.meta.view_prefix,
        constants.PUBLIC_SUBMISSIONS_VIEW_PREFIX.rstrip("/"),
    )
    return sorted(
        (method, route.path)
        for route in iter_route_contexts(app.routes)
        if route.path and route.path.startswith(prefixes)
        for method in route.methods or ()
    )
