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
from simple_module_core.csp import CspSourceRegistry
from simple_module_core.health import HealthCheck, HealthCheckResult, HealthRegistry, HealthStatus
from simple_module_core.menu import MenuRegistry
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_core.resources import ResourceTypeRegistry

from sm_images.core import constants

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
        # ``tippecanoe_path`` as booted (a restart field); the health check asks.
        self.tippecanoe_path = "tippecanoe"

    def register_settings(self, app: FastAPI) -> None:
        """Register the settings class and mount the services container.

        ``register_module_settings`` records the class so the host can hydrate
        it from the DB at lifespan start - it assigns the result onto the
        container this creates, which is why every later read goes through
        ``app.state.sm_images`` rather than a captured local.
        """
        from settings.registration import register_module_settings

        from sm_images.core.settings import ImagesSettings
        from sm_images.web.services import ImagesServices

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
        from sm_images.core.access import resource_types

        resource_types.register(registry)

    def register_menu_items(self, registry: MenuRegistry) -> None:
        from sm_images.web.endpoints import menu

        menu.register(registry)

    def register_middleware(self, app: FastAPI) -> None:
        """Remember the current request for the ``images.collection`` sharing
        loader, which the framework calls without one (``request_context``)."""
        from sm_images.core.tenancy.request_context import RequestContextMiddleware

        app.add_middleware(RequestContextMiddleware)

    def register_health_checks(self, registry: HealthRegistry) -> None:
        """``images.tippecanoe``: degraded while the binary that builds map tiles
        cannot be found. Points still work; no PMTiles archive is built."""
        registry.add(HealthCheck(name="images.tippecanoe", check=self._tippecanoe_health))

    async def _tippecanoe_health(self) -> HealthCheckResult:
        from sm_images.map import pmtiles_build

        if pmtiles_build.locate(self.tippecanoe_path) is not None:
            return HealthCheckResult(HealthStatus.HEALTHY)
        return HealthCheckResult(
            HealthStatus.DEGRADED,
            f"tippecanoe not found ({self.tippecanoe_path!r}): map tiles are not built",
        )

    def register_exception_handlers(self, app: FastAPI) -> None:
        from sm_images.core.errors import install_exception_handlers

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

    def register_csp_sources(self, registry: CspSourceRegistry) -> None:
        """Allow the map's basemap host (``map_style_url``'s origin).

        A provider, evaluated per response from the hydrated settings: this
        runs before they hydrate, and an edit then applies with no restart.
        """
        from sm_images.map.style import csp_sources

        registry.add_provider(csp_sources)

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.LOCALE_NAMESPACE: base}

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        # Imported here, not at module top: the entry point must resolve for
        # Alembic autogenerate and the doctor even when the routers cannot be
        # built yet.
        from sm_images.web.endpoints.api import router as api
        from sm_images.web.endpoints.public import router as public
        from sm_images.web.endpoints.views import router as views

        api_router.include_router(api)
        # Beside the admin router, not in it: anonymous, so without its tenant
        # binding and CSRF check - ``bind_public`` instead.
        api_router.include_router(public)
        view_router.include_router(views)

    async def on_startup(self, app: FastAPI) -> None:
        """Everything that needs the hydrated settings and an open database:
        the tenancy mode, the CDN base public URLs use, the fail-closed guard,
        the session factory object intents commit through on their own, the
        step registry (built-ins and every installed plugin's
        ``images_extensions``, then frozen), the runtime the pipeline's
        after-commit dispatch runs on, and the ``images.storage_bytes`` gauge
        on billing's registry when billing runs."""
        from sm_images.core import billing, tenancy
        from sm_images.core.storage import intents
        from sm_images.ingest.imports import log_redact
        from sm_images.pipeline.extensions import load_extensions
        from sm_images.web.serving import urls

        log_redact.install()

        setattr(app.state, constants.MODULE_ATTR, self)
        billing.register_meter(app)
        mode = tenancy.configure(app)
        settings = getattr(app.state, constants.PACKAGE).settings
        urls.configure(settings.public_asset_base_url, mode)
        self.tippecanoe_path = settings.tippecanoe_path
        load_extensions()
        self.mount_public_pages(app)
        sm = getattr(app.state, "sm", None)
        db = getattr(sm, "db", None)
        if (session_class := getattr(db, "sync_session_class", None)) is not None:
            tenancy.install_guard(session_class)
        if (factory := getattr(db, "session_factory", None)) is not None:
            intents.use_session_factory(factory)
            self._use_runtime(app, factory)

    @staticmethod
    def mount_public_pages(app: FastAPI) -> None:
        """``/images/c/{slug}`` at the app root, beside the console's prefix
        (``register_routes`` hands out only prefixed routers)."""
        from fastapi.routing import iter_route_contexts

        from sm_images.web.endpoints.public_views import router

        # Once per app: ``on_startup`` runs again on a lifespan restart.
        page = f"{constants.PUBLIC_COLLECTION_PREFIX.rstrip('/')}/{{slug}}"
        if not any(r.path == page for r in iter_route_contexts(app.routes)):
            app.include_router(router)

    async def on_shutdown(self, app: FastAPI) -> None:
        """Forget the runtime: a lifespan restart in one process (tests, dev
        reload) must not dispatch through the previous app's engine."""
        from sm_images.pipeline.runtime import use_runtime

        use_runtime(None)

    @staticmethod
    def _use_runtime(app: FastAPI, factory: object) -> None:
        from simple_module_hosting.tenancy import TenancyMode, tenancy_mode

        from sm_images.core.storage import store_for
        from sm_images.pipeline.runtime import Runtime, use_runtime

        use_runtime(
            Runtime(
                session_factory=factory,
                store=lambda: store_for(app),
                settings=lambda: getattr(app.state, constants.PACKAGE).settings,
                bus=lambda: getattr(getattr(app.state, "sm", None), "event_bus", None),
                # Anything not clearly single-tenant is multi: fail closed.
                multi_tenant=lambda: tenancy_mode(app) is not TenancyMode.SINGLE,
            )
        )
