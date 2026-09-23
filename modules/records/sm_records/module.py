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
from simple_module_core.health import HealthRegistry
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_core.module import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

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
        self._menu_synced_at = 0.0

    @property
    def reduce_drift(self) -> dict[int, dict[str, int]]:
        """What the last in-process verify found, by type id (Phase 5 §5.2).

        Exposed on the module instance because that is where a host looks for
        this module's runtime state, and because the health check already
        closes over ``self`` — the state itself lives in
        :mod:`sm_records.index._drift`, which is process-global for the same
        reason the provider registry is: the writer has no module instance to
        report to. Empty means the last verify was clean, or that none has run
        in this process.
        """
        from sm_records.index._drift import current_drift

        return current_drift()

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
        # ``label_key`` is not on the released framework's ``MenuItem`` yet
        # (0.0.26); the literal label stands until it is, as in every sibling.
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
                label="All record types",
                url=constants.MENU_URL,
                icon=constants.MENU_ICON,
                order=constants.MENU_ORDER,
                section=MenuSection.ADMIN_SIDEBAR,
                group=constants.MENU_GROUP_TYPES,
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
        """Nothing here — the exemption is added at startup instead.

        Which path is public depends on ``public_route_prefix``, and this hook
        runs during app construction, before the host hydrates that from the
        database. Exempting the pydantic default here would open a prefix the
        operator may have moved, and leave the one they chose gated.

        ``AuthMiddleware`` reads the registry live, so
        :func:`sm_records.boot.exempt_public_routes` can fill it from
        ``on_startup`` — after hydration, before the first request. Design §10.
        """

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
        """Hand the health check what it cannot reach on its own.

        ``register_health_checks`` runs before the lifespan opens the database,
        and module settings are hydrated from the DB at lifespan start — so the
        check closes over *this instance* and reads both from here, once they
        exist. Storing them rather than capturing ``app`` keeps the check free
        of the request/app object entirely, which is what lets a test call it
        with a module whose ``db`` is a bare ``DatabaseState``.

        ``settings`` is overwritten with the hydrated object: it was either
        ``None`` or a test's pre-seeded stand-in until now, and the check wants
        ``reindex_stale_after_seconds`` as the operator set it.
        """
        self.db = getattr(app.state, "sm", None) and app.state.sm.db
        services = getattr(app.state, constants.PACKAGE, None)
        if services is not None and getattr(services, "settings", None) is not None:
            self.settings = services.settings

        # The anonymous read API (design §10), mounted and exempted here for
        # the reason in ``boot``'s docstring: its prefix is a DB-backed setting
        # that only exists as the operator set it from this point on.
        from sm_records import boot
        from sm_records.settings import RecordsSettings

        settings = self.settings or RecordsSettings()
        boot.mount_public_router(app, settings)
        boot.exempt_public_routes(app, settings)
        # The media library the ``media`` picker calls, found by route shape
        # (never by importing it) — :mod:`sm_records.media`. Same reason as above.
        from sm_records import media

        media.configure(app, settings.media_api_prefix)

        # Dropping a content locale is not refused at save (``settings_checks``
        # says why), so this is what makes the records left behind visible. Once
        # per boot: the framework offers no hook to re-run it when an operator
        # hydrates new settings, which the health check's docstring records.
        if self.db is not None:
            from sm_records.health import count_orphaned_locales

            self.orphaned_locales = await count_orphaned_locales(self.db, settings)

        # The first sidebar read: ``register_menu_items`` ran before there was
        # a database, so until now the registry holds the hub entry and none
        # of the per-type ones. Forced past the refresh window because there
        # is nothing to be stale yet — and deliberately last, so a database
        # this cannot read costs a log line rather than a boot.
        from sm_records import menu

        await menu.refresh(self, force=True)

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.PERM_GROUP: base}

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        # Imported here, not at module top: the entry point must resolve for
        # Alembic autogenerate and the doctor even when the routers cannot be
        # built yet, and a top-level import would make one missing dependency
        # take the whole module — and its tables — out of discovery.
        from sm_records.endpoints.api import router as api
        from sm_records.endpoints.views import router as views

        api_router.include_router(api)
        view_router.include_router(views)
