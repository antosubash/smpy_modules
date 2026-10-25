"""Records module — admin-defined content types stored as JSON documents.

A YesSql-style document/index split: one document table holds every record's
payload, and typed index tables make declared fields queryable. No table is
ever created at runtime. Design: ``docs/plans/2026-09-19-records-module-design.md``.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
from pathlib import Path
from typing import TYPE_CHECKING

from fastapi import APIRouter
from simple_module_core.events import EventBus
from simple_module_core.health import HealthRegistry
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry
from simple_module_core.rate_limit import RateLimitRegistry, RateLimitRule

from sm_records import constants

if TYPE_CHECKING:
    from fastapi import FastAPI

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only; a hardcoded string
# here would silently fall behind it.
_VERSION = importlib.metadata.version(constants.DISTRIBUTION)


class RecordsModule(ModuleBase):
    meta = ModuleMeta(
        name=constants.MODULE_NAME,
        route_prefix=constants.ROUTE_PREFIX_API,
        view_prefix=constants.VIEW_PREFIX,
        depends_on=[constants._MODULE_SETTINGS],
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) — this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def __init__(self) -> None:
        super().__init__()
        # Pre-seeding this is how a test pins settings without a database:
        # ``register_settings`` hands it to the services container instead of
        # the pydantic defaults, and with no hydration step to overwrite it,
        # it is what every hook then reads.
        self.settings = None
        # Set in ``on_startup``; the health check reads it and answers HEALTHY
        # while it is ``None`` (there is nothing to be stale during boot).
        self.db = None
        # ``{locale: records}`` for languages this install no longer publishes,
        # counted once at startup — see :mod:`sm_records.health`.
        self.orphaned_locales: dict[str, int] = {}
        # The sidebar state of :mod:`sm_records.menu`: the registry handed to
        # ``register_menu_items``, the per-type items this module last put in
        # it, and when. Kept here because the registry is built once at boot
        # and the types it describes are created at runtime — the module
        # instance is the only thing that outlives both.
        self.menu_registry: MenuRegistry | None = None
        self._type_menu_items: list[MenuItem] = []
        self._menu_dirty = False
        self._menu_suppressed = False  # a mounted request with no tenancy answer (#210)
        self._menu_synced_at = 0.0

    def register_settings(self, app: FastAPI) -> None:
        """Register the settings class and mount the services container.

        ``register_module_settings`` records the class so the host can hydrate
        it from the DB at lifespan start — it assigns the result onto the
        container this creates, which is why every later read goes through
        ``app.state.sm_records`` rather than a captured local.

        It is also where the **collection registry is sealed** (Phase 5 §6.1).
        This is the first hook the host calls, so by the time it runs the
        host's own ``declare_collection`` calls have long since happened at
        import; anything declaring one after this point would be creating
        tables that no migration wrote and no ``create_all`` reached, and
        every write to them would be a ``no such table`` found at runtime
        rather than a ``RuntimeError`` found at boot.
        """
        from settings.registration import register_module_settings

        from sm_records.models._tables import seal

        seal()

        from sm_records.services import RecordsServices
        from sm_records.settings import RecordsSettings

        register_module_settings(
            app,
            constants.PACKAGE,
            RecordsSettings,
            lambda defaults: RecordsServices(settings=self.settings or defaults),
        )

    def register_permissions(self, registry: PermissionRegistry) -> None:
        """Three static permissions — the only ones the role editor can show.

        Per-type access (``RecordType.allowed_roles``) narrows these at request
        time and is invisible here: ``register_permissions`` runs before the
        database is open, and types are created at runtime. Design doc §10.
        """
        registry.add_group(
            constants.PERM_GROUP,
            [constants.PERM_VIEW, constants.PERM_EDIT, constants.PERM_MANAGE_TYPES],
        )

    def register_menu_items(self, registry: MenuRegistry) -> None:
        """Deliberately not role-gated: menu role filtering is a plain
        intersection with no admin bypass, so listing roles here would hide
        the entry from an ``admin`` user. The views carry their own
        permission dependencies."""
        # ``MenuItem`` has ``label_key`` since framework 0.0.35; the literal
        # label stands until the repo-wide UI i18n conversion (CLAUDE.md).
        # U17: this used to sit in the shared "Content" group, a header away
        # from the per-type entries it is the hub for — the parent read as a
        # peer of another module's screen rather than what it actually is.
        # It now shares its children's own "Records" group, first by
        # ``order`` (below ``MENU_ORDER_TYPE``, and the registry's sort is
        # stable), and named for what that makes it: not a screen of its
        # own so much as the way into every type that doesn't have its own
        # entry.
        registry.add(
            MenuItem(
                label=constants.MENU_LABEL,
                label_key=constants.MENU_LABEL_KEY,
                url=constants.MENU_URL,
                icon=constants.MENU_ICON,
                order=constants.MENU_ORDER,
                section=MenuSection.ADMIN_SIDEBAR,
                group=constants.MENU_GROUP_TYPES,
                group_key=constants.MENU_GROUP_KEY_TYPES,
            )
        )
        # Kept, because a type opting into its own entry (``show_in_menu``) is
        # a runtime fact and this hook runs once, at boot, before there is a
        # database to ask. :mod:`sm_records.menu` fills the rest in later and
        # keeps it current; the hub item above is never one of its items.
        self.menu_registry = registry

    def mark_menu_dirty(self) -> None:
        """Re-read the sidebar types on the next request that renders one.

        Called through :func:`sm_records.menu.mark_dirty` by the endpoints
        that write a type. It is a flag and not a refresh: the write has not
        committed yet when they call it (the framework commits after the
        response starts), so reading now would read the row as it was.
        """
        self._menu_dirty = True

    def register_health_checks(self, registry: HealthRegistry) -> None:
        """A reindex orphaned by a worker restart is recoverable but silent —
        the field just refuses filters until someone runs the CLI. This
        degrades /health/ready when a ``reindex_pending`` entry is older
        than ``reindex_stale_after_seconds``. Design doc §8.9."""
        from sm_records.health import stale_reindex_check

        registry.add(stale_reindex_check(self))

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """The read API's exemption is added at startup instead.

        Which path is public depends on ``public_route_prefix``, and this hook
        runs during app construction, before the host hydrates that from the
        database. Exempting the pydantic default here would open a prefix the
        operator may have moved, and leave the one they chose gated.

        ``AuthMiddleware`` reads the registry live, so
        :func:`sm_records.boot.exempt_public_routes` can fill it from
        ``on_startup`` — after hydration, before the first request. Design §10.

        The website-submission routes (#101) are the exception: their prefix
        is fixed, so they are exempted here, for ``GET`` and ``POST`` only.
        """
        registry.add_prefix(
            constants.PUBLIC_SUBMISSIONS_API_PREFIX,
            methods=set(constants.PUBLIC_SUBMISSIONS_ROUTE_METHODS),
        )

    def register_middleware(self, app: FastAPI) -> None:
        """Install the deferred-job drain and the sidebar sync.

        The drain is :mod:`sm_records.deferred`: the reindex of §8.9 must not
        start until the request that scheduled it has committed and released
        its session, and middleware is the first hook that runs after a
        route's dependency teardown. A ``BackgroundTasks`` entry runs *inside*
        it, which on SQLite deadlocks the schema write against its own
        rebuild.

        The sync is :mod:`sm_records.menu`, and middleware for a different
        reason — see below.

        The body guard is :mod:`sm_records._body_limit`, and middleware
        because a router dependency runs *after* FastAPI has read and parsed
        the body for the endpoint's model — which is the cost it exists to
        avoid. The framework offers nothing shared to hook into here.
        """
        from sm_records._body_limit import BodyLimitMiddleware
        from sm_records._menu_middleware import MenuSyncMiddleware
        from sm_records.deferred import DeferredJobsMiddleware

        app.add_middleware(DeferredJobsMiddleware)
        # Added before the two below so it ends up *outside* them
        # (``add_middleware`` is LIFO): a body this module will not read must
        # not have a sidebar sync or a deferred-job drain wrapped around it.
        app.add_middleware(BodyLimitMiddleware)
        # Parked before the middleware that reads it so a handler can reach
        # this instance through ``request.app`` — today only to mark the
        # sidebar stale after a type write (:func:`sm_records.menu.mark_dirty`).
        setattr(app.state, constants.MODULE_ATTR, self)
        # Keeps the per-type sidebar entries current in *this* worker, which
        # is the half of :mod:`sm_records.menu` that a multi-process host
        # needs: the registry is per process, and only one process served the
        # write. Added here rather than wrapped around a route because it has
        # to run before ``InertiaLayoutDataMiddleware`` reads the registry —
        # see :mod:`sm_records._menu_middleware`.
        app.add_middleware(MenuSyncMiddleware, module=self)

    async def on_startup(self, app: FastAPI) -> None:
        """Everything that needs the hydrated settings and an open database —
        the tenancy guard, the anonymous read API, the media picker, the
        orphaned-locale count and the first sidebar read. The body is
        :func:`sm_records.boot.startup`, which says why each runs here."""
        from sm_records import boot

        await boot.startup(self, app)

    async def on_shutdown(self, app: FastAPI) -> None:
        """Stop the pattern-check workers (``sm_records._pattern_worker``)."""
        from sm_records import _pattern_worker

        await _pattern_worker.close()

    def register_event_handlers(self, bus: EventBus, app: FastAPI | None = None) -> None:
        """The outbox handler that mails a website submission's notification
        (#101), when the host delivers durably. Registered whatever ``app`` is:
        the outbox worker builds modules with ``app=None`` and still has to
        know the handler. See :mod:`sm_records.public_submissions.mail_runner`."""
        from sm_records.public_submissions.mail_runner import (
            HANDLER_NAME,
            NotificationDue,
            durable_handler,
        )

        bus.subscribe_durable(NotificationDue, durable_handler(self), name=HANDLER_NAME)

    def register_rate_limits(self, registry: RateLimitRegistry) -> None:
        """A static backstop on the anonymous form definition. Submits are
        limited by the module itself, at rates that are settings."""
        registry.add_prefix(
            constants.PUBLIC_SUBMISSIONS_API_PREFIX,
            RateLimitRule("60/minute", key="ip", methods=frozenset({"GET"})),
        )

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.PERM_GROUP: base}

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        # Imported here, not at module top: the entry point must resolve for
        # Alembic autogenerate and the doctor even when the routers cannot be
        # built yet, and a top-level import would make one missing dependency
        # take the whole module — and its tables — out of discovery.
        from sm_records.endpoints.api import router as api
        from sm_records.endpoints.api.public_submissions_public import router as submissions
        from sm_records.endpoints.views import router as views

        api_router.include_router(api)
        # Beside the admin router, not in it: anonymous, so without its tenant
        # binding and CSRF check (``endpoints.api.public_submissions_public``).
        prefix = constants.PUBLIC_SUBMISSIONS_API_PREFIX.removeprefix(constants.ROUTE_PREFIX_API)
        api_router.include_router(submissions, prefix=prefix.rstrip("/"))
        view_router.include_router(views)
