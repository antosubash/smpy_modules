"""Images module - collections of images with a processing pipeline.

Originals are immutable; every derived artefact comes from a pipeline step run
as a background task. Design:
``docs/superpowers/specs/2026-10-28-images-module-design.md``.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter
from simple_module_core.body_limits import BodyLimitRegistry
from simple_module_core.menu import MenuRegistry
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_core.resources import ResourceTypeRegistry

from sm_images import constants

if TYPE_CHECKING:
    from fastapi import FastAPI

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only.
_VERSION = importlib.metadata.version(constants.DISTRIBUTION)


class ImagesModule(ModuleBase):
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
        # The host's tenancy mode, set by ``on_startup``; the sharing loader
        # reads it (``resource_types``), and ``None`` before startup fails closed.
        self.tenancy = None

    def register_settings(self, app: FastAPI) -> None:
        """Register the settings class and mount the services container.

        ``register_module_settings`` records the class so the host can hydrate
        it from the DB at lifespan start - it assigns the result onto the
        container this creates, which is why every later read goes through
        ``app.state.sm_images`` rather than a captured local.
        """
        from settings.registration import register_module_settings

        from sm_images.services import ImagesServices
        from sm_images.settings import ImagesSettings

        register_module_settings(
            app,
            constants.PACKAGE,
            ImagesSettings,
            lambda defaults: ImagesServices(settings=self.settings or defaults),
        )

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(
            constants.PERM_GROUP, list(constants.PERMISSIONS), label_key=constants.PERM_GROUP_KEY
        )

    def register_resource_types(self, registry: ResourceTypeRegistry) -> None:
        from sm_images import resource_types

        resource_types.register(registry, lambda: self.tenancy)

    def register_menu_items(self, registry: MenuRegistry) -> None:
        from sm_images import menu

        menu.register(registry)

    def register_exception_handlers(self, app: FastAPI) -> None:
        from sm_images.errors import install_exception_handlers

        install_exception_handlers(app)

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """Anonymous reads only: a prefix per public surface, ``GET``/``HEAD``.

        Fixed prefixes (unlike records', which a setting moves), so they are
        exempted here. Terminated with ``/`` so a prefix never matches the
        admin API or console.
        """
        for prefix in constants.PUBLIC_PREFIXES:
            registry.add_prefix(prefix, methods=set(constants.PUBLIC_METHODS))

    def register_body_limits(self, registry: BodyLimitRegistry) -> None:
        """Raise the global body ceiling on the upload routes to
        ``upload_body_max_bytes`` plus multipart framing.

        The limit is a callable, evaluated per request, so a Settings-screen
        edit applies at once and needs no restart even though the routes are
        registered during app construction.
        """

        def ceiling(app: FastAPI) -> int:
            services = getattr(app.state, constants.PACKAGE)
            return services.settings.upload_body_max_bytes + constants.MULTIPART_OVERHEAD_BYTES

        methods = set(constants.UPLOAD_METHODS)
        for pattern in constants.UPLOAD_ROUTE_PATTERNS:
            registry.add_regex(pattern, ceiling, methods=methods)
        for prefix in constants.UPLOAD_PREFIXES:
            registry.add_prefix(prefix, ceiling, methods=methods)

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.LOCALE_NAMESPACE: base}

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        # Imported here, not at module top: the entry point must resolve for
        # Alembic autogenerate and the doctor even when the routers cannot be
        # built yet.
        from sm_images.endpoints.api import router as api
        from sm_images.endpoints.views import router as views

        api_router.include_router(api)
        view_router.include_router(views)

    async def on_startup(self, app: FastAPI) -> None:
        """Everything that needs the hydrated settings and an open database:
        the tenancy mode, the fail-closed guard, and the session factory object
        intents commit through on their own."""
        from sm_images import intents, tenancy

        setattr(app.state, constants.MODULE_ATTR, self)
        self.tenancy = tenancy.configure(app)
        db = getattr(getattr(app.state, "sm", None), "db", None)
        if (session_class := getattr(db, "sync_session_class", None)) is not None:
            tenancy.install_guard(session_class)
        if (factory := getattr(db, "session_factory", None)) is not None:
            intents.use_session_factory(factory)
