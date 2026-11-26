"""Events module - calendars and events, with recurrence, sharing and public pages."""

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
        i18n_audience="admin",
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
        self._install_secret(app)

    @staticmethod
    def _install_secret(app: FastAPI) -> None:
        """The running app's secret wins over the environment for the stored-secret crypto (hosts
        may inject it through ``create_app(settings=...)``). Resolved lazily, because
        ``app.state.sm`` is assigned after this phase, and through a weakref, because the
        provider is process-global and must not keep a discarded app alive."""
        from sm_events.core import crypto

        app_ref = weakref.ref(app)

        def live_secret() -> str:
            live_app = app_ref()
            if live_app is None:
                return ""
            sm = getattr(live_app.state, "sm", None)
            return getattr(getattr(sm, "settings", None), "secret_key", "") or ""

        crypto.set_secret_provider(live_secret)

    def register_exception_handlers(self, app: FastAPI) -> None:
        from sm_events.core.errors import install_exception_handlers

        install_exception_handlers(app)

    async def on_startup(self, app: FastAPI) -> None:
        """The tenancy mode, read off the built middleware stack, the fail-closed guard on
        the framework's session class (as images does), and, once the settings are hydrated,
        the public routes: where they mount and in which languages depend on the database. The log
        filter that keeps a private feed token out of every request log goes on first."""
        from sm_events.calendar.plugins.extensions import load_extensions
        from sm_events.core import boot, tenancy
        from sm_events.feeds.tokens import log_redact

        log_redact.install()  # first: nothing below may log a request before the filter is on
        tenancy.configure(app)
        db = getattr(getattr(app.state, "sm", None), "db", None)
        if (session_class := getattr(db, "sync_session_class", None)) is not None:
            tenancy.install_guard(session_class)
        boot.wire_public(app)
        load_extensions()  # the registry: built-ins, then every plugin's, then frozen

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
        host's general ``rate_limit_authenticated``. So do the reminder follow writes."""
        from sm_events.web.endpoints import reminders_api, shares_api, subscriptions_api

        registry.add_regex(
            shares_api.PATH_PATTERN,
            RateLimitRule(shares_api.RATE, key="user", methods=frozenset({"GET"})),
        )
        registry.add_regex(
            subscriptions_api.PATH_PATTERN,
            RateLimitRule(subscriptions_api.RATE, key="user", methods=frozenset({"POST", "PATCH"})),
        )
        registry.add_regex(
            reminders_api.PATH_PATTERN,
            RateLimitRule(reminders_api.RATE, key="user", methods=frozenset({"PUT", "DELETE"})),
        )
        registry.add_regex(
            reminders_api.BY_ID_PATTERN,
            RateLimitRule(reminders_api.RATE, key="user", methods=frozenset({"DELETE"})),
        )

    def register_event_handlers(self, bus: EventBus, app: FastAPI | None = None) -> None:
        """Private feed links and reminder follows go when their user, membership or tenant do.
        A worker builds no
        app (``app`` is ``None``) and has nothing to subscribe: a link whose owner is gone
        serves nothing anyway, so this only removes the rows."""
        if app is None:
            return
        from sm_events.feeds.tokens import cleanup
        from sm_events.reminders import cleanup as reminder_cleanup

        cleanup.subscribe(bus, app)
        reminder_cleanup.subscribe(bus, app)

    def register_body_limits(self, registry: BodyLimitRegistry) -> None:
        """The import upload's body ceiling: the largest file an operator may allow plus 1 MiB of
        multipart framing. It runs before settings hydrate, so it cannot read ``import_max_bytes``;
        the handler enforces the stored cap (clamped) while it reads."""
        registry.add_regex(
            rf"^{constants.ROUTE_PREFIX_API}/imports/?$",
            constants.IMPORT_BODY_CEILING + constants.IMPORT_MIB,
            methods={"POST"},
        )

    def register_middleware(self, app: FastAPI) -> None:
        """Remember the current request for the ``events.calendar`` loader, which
        the framework's sharing router calls without one."""
        from sm_events.core.tenancy.request_context import RequestContextMiddleware
        from sm_events.web.no_store import NoStoreSubscriptions

        app.add_middleware(RequestContextMiddleware)
        app.add_middleware(NoStoreSubscriptions)

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
