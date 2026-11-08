"""Newsletter module - lists live in records; campaigns are sent over SMTP."""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import weakref
from pathlib import Path

from fastapi import APIRouter, Depends, FastAPI
from simple_module_core.body_limits import BodyLimitRegistry
from simple_module_core.events import EventBus
from simple_module_core.menu import MenuRegistry
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_core.rate_limit import RateLimitRegistry, RateLimitRule

from sm_newsletter.core import constants

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only.
_VERSION = importlib.metadata.version(constants.DISTRIBUTION)

# The unsubscribe link's per-IP rates (S9). The POST is generous: one-click
# posts arrive from mailbox providers' shared egress IPs, and a refused one
# loses an opt-out. A forged token costs one HMAC and no query.
_UNSUBSCRIBE_RATES = {"GET": "60/minute", "POST": "300/minute"}
# The open pixel and the click redirect, per IP, GET only (T11): image proxies
# fetch pixels from shared egress IPs right after a send, and a refused click
# breaks a reader's navigation.
_TRACKING_RATES = {constants.OPEN_PREFIX: "600/minute", constants.CLICK_PREFIX: "300/minute"}


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
            # would store ``smtp_password`` in plaintext.
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
        """The email logo (C8): anonymous, ``GET`` only, at a fixed path. The
        unsubscribe links (S9): anonymous ``GET`` and ``POST``, each method with
        its own anonymous rate, which replaces the host's ``rate_limit_public``
        (120/minute by default) - that one would cap the POST below its 300.
        The open pixel and click redirect (T11): anonymous ``GET``, likewise."""
        registry.add_exact(constants.BRAND_LOGO_PATH, methods={"GET"})
        for method, rate in _UNSUBSCRIBE_RATES.items():
            registry.add_prefix(constants.UNSUBSCRIBE_PREFIX, methods={method}, rate=rate)
        for prefix, rate in _TRACKING_RATES.items():
            registry.add_prefix(prefix, methods={"GET"}, rate=rate)

    def register_rate_limits(self, registry: RateLimitRegistry) -> None:
        """The same per-IP rates for every caller, signed in or not (S9, T11)."""
        for method, rate in _UNSUBSCRIBE_RATES.items():
            registry.add_prefix(
                constants.UNSUBSCRIBE_PREFIX,
                RateLimitRule(rate, key="ip", methods=frozenset({method})),
            )
        for prefix, rate in _TRACKING_RATES.items():
            registry.add_prefix(prefix, RateLimitRule(rate, key="ip", methods=frozenset({"GET"})))

    @staticmethod
    def mount_public_routes(app: FastAPI) -> None:
        """Newsletter's public routes at the app root (``register_routes`` hands
        out only prefixed routers). Each router once per app, guarded by its own
        path: ``on_startup`` runs again on a lifespan restart."""
        from fastapi.routing import iter_route_contexts

        from sm_newsletter.web.endpoints import brand, tracking, unsubscribe

        mounted = {r.path for r in iter_route_contexts(app.routes)}
        for path, router in (
            (constants.BRAND_LOGO_PATH, brand.router),
            (unsubscribe.PATH, unsubscribe.router),
            (tracking.OPEN_PATH, tracking.router),
        ):
            if path not in mounted:
                app.include_router(router)

    def register_body_limits(self, registry: BodyLimitRegistry) -> None:
        """Raise the body ceiling on the import upload to ``MAX_UPLOAD_BYTES`` plus 1 MiB of
        multipart framing (R7)."""
        from sm_newsletter.imports.constants import MAX_UPLOAD_BYTES, MiB

        registry.add_regex(
            rf"^{constants.ROUTE_PREFIX_API}/imports/?$", MAX_UPLOAD_BYTES + MiB, methods={"POST"}
        )

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
