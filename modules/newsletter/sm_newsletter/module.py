"""Newsletter module - lists live in records; campaigns are sent over SMTP."""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import weakref
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from simple_module_core.events import EventBus
from simple_module_core.menu import MenuRegistry
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from sm_newsletter.core import constants

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only.
_VERSION = importlib.metadata.version(constants.DISTRIBUTION)


class NewsletterModule(ModuleBase):
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

        from sm_newsletter.core import crypto
        from sm_newsletter.core.services import NewsletterServices
        from sm_newsletter.core.settings import NewsletterSettings

        register_module_settings(
            app,
            constants.PACKAGE,
            NewsletterSettings,
            lambda defaults: NewsletterServices(settings=self.settings or defaults),
            # The generic Settings screen links here and refuses writes: it
            # would store ``smtp_password`` in plaintext. PR 3 adds the page.
            manage_url=constants.SETTINGS_URL,
        )

        # The running app's secret wins (hosts may inject it through
        # ``create_app(settings=...)``). Resolved lazily - app.state.sm is
        # assigned after this phase - and through a weakref, because the
        # provider is process-global and must not keep a discarded app alive.
        app_ref = weakref.ref(app)

        def _live_secret() -> str:
            live_app = app_ref()
            if live_app is None:
                return ""
            sm = getattr(live_app.state, "sm", None)
            return getattr(getattr(sm, "settings", None), "secret_key", "") or ""

        crypto.set_secret_provider(_live_secret)

    def register_exception_handlers(self, app: FastAPI) -> None:
        from sm_newsletter.core.errors import install_exception_handlers

        install_exception_handlers(app)

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from simple_module_hosting.csrf import RequiresCsrf

        from sm_newsletter.web.endpoints import build_api_router
        from sm_newsletter.web.endpoints.views import router as views

        # The framework's CSRF check on every write; reads pass.
        api_router.include_router(build_api_router(), dependencies=[Depends(RequiresCsrf())])
        view_router.include_router(views)

    def register_menu_items(self, registry: MenuRegistry) -> None:
        from sm_newsletter.web.endpoints.menu import menu_items

        registry.add_many(menu_items())

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """The email logo (C8): anonymous, ``GET`` only, at a fixed path."""
        registry.add_exact(constants.BRAND_LOGO_PATH, methods={"GET"})

    @staticmethod
    def mount_public_routes(app: FastAPI) -> None:
        """Newsletter's public routes at the app root (``register_routes`` hands
        out only prefixed routers). Once per app: ``on_startup`` runs again on a
        lifespan restart."""
        from fastapi.routing import iter_route_contexts

        from sm_newsletter.web.endpoints.brand import router

        if not any(r.path == constants.BRAND_LOGO_PATH for r in iter_route_contexts(app.routes)):
            app.include_router(router)

    def register_event_handlers(self, bus: EventBus, app: FastAPI | None = None) -> None:
        """Mirror records' ``SubscriptionChanged`` into the suppression store.

        Nothing without ``app``: the outbox worker builds modules with none,
        and the mirror writes through the web app's session factory."""
        if app is None:
            return
        from sm_newsletter.core.suppression import mirror

        mirror.subscribe(bus, app)

    async def on_startup(self, app: FastAPI) -> None:
        """The tenancy mode, read off the built middleware stack, the public
        routes, and the fail-closed guard on the framework's session class - as
        images does."""
        from sm_newsletter.core import tenancy

        tenancy.configure(app)
        self.mount_public_routes(app)
        db = getattr(getattr(app.state, "sm", None), "db", None)
        if (session_class := getattr(db, "sync_session_class", None)) is not None:
            tenancy.install_guard(session_class)

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(
            constants.PERM_GROUP, list(constants.PERMISSIONS), label_key=constants.PERM_GROUP_KEY
        )

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.LOCALE_NAMESPACE: base}
