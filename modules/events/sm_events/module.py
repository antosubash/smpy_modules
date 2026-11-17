"""Events module - calendars and events, with recurrence, sharing and public pages."""

from __future__ import annotations

import importlib.metadata
import importlib.resources
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from simple_module_core.menu import MenuRegistry
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.rate_limit import RateLimitRegistry, RateLimitRule
from simple_module_core.resources import ResourceTypeRegistry

from sm_events.core import constants

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only.
_VERSION = importlib.metadata.version(constants.DISTRIBUTION)


class EventsModule(ModuleBase):
    meta = ModuleMeta(
        name=constants.MODULE_NAME,
        route_prefix=constants.ROUTE_PREFIX_API,
        view_prefix=constants.VIEW_PREFIX,
        depends_on=list(constants.DEPENDS_ON),
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) - this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def __init__(self) -> None:
        super().__init__()
        # Pre-seeding this is how a test pins settings without a database:
        # ``register_settings`` hands it to the services container instead of
        # the pydantic defaults.
        self.settings = None

    def register_settings(self, app: FastAPI) -> None:
        from simple_module_core.module_settings import register_module_settings

        from sm_events.core.services import EventsServices
        from sm_events.core.settings import EventsSettings

        register_module_settings(
            app,
            constants.PACKAGE,
            EventsSettings,
            lambda defaults: EventsServices(settings=self.settings or defaults),
        )

    def register_exception_handlers(self, app: FastAPI) -> None:
        from sm_events.core.errors import install_exception_handlers

        install_exception_handlers(app)

    async def on_startup(self, app: FastAPI) -> None:
        """The tenancy mode, read off the built middleware stack, and the
        fail-closed guard on the framework's session class - as images does."""
        from sm_events.core import tenancy

        tenancy.configure(app)
        db = getattr(getattr(app.state, "sm", None), "db", None)
        if (session_class := getattr(db, "sync_session_class", None)) is not None:
            tenancy.install_guard(session_class)

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from simple_module_hosting.csrf import RequiresCsrf

        from sm_events.web.endpoints import build_api_router, views

        # The framework's CSRF check on every write; reads pass.
        api_router.include_router(build_api_router(), dependencies=[Depends(RequiresCsrf())])
        view_router.include_router(views.router)

    def register_menu_items(self, registry: MenuRegistry) -> None:
        from sm_events.web.endpoints.menu import menu_items

        for item in menu_items():
            registry.add(item)

    def register_rate_limits(self, registry: RateLimitRegistry) -> None:
        """The share dialog's user picker, per signed-in user: it is a search of
        the user directory, so it gets a budget of its own rather than the
        host's general ``rate_limit_authenticated``."""
        from sm_events.web.endpoints import shares_api

        registry.add_regex(
            shares_api.PATH_PATTERN,
            RateLimitRule(shares_api.RATE, key="user", methods=frozenset({"GET"})),
        )

    def register_middleware(self, app: FastAPI) -> None:
        """Remember the current request for the ``events.calendar`` loader, which
        the framework's sharing router calls without one."""
        from sm_events.core.tenancy.request_context import RequestContextMiddleware

        app.add_middleware(RequestContextMiddleware)

    def register_resource_types(self, registry: ResourceTypeRegistry) -> None:
        from sm_events.core.access import resource_types

        resource_types.register(registry)

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(
            constants.PERM_GROUP, list(constants.PERMISSIONS), label_key=constants.PERM_GROUP_KEY
        )

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.LOCALE_NAMESPACE: base}
