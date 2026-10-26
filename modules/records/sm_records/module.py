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
from sm_records._module_submissions import SubmissionHooks

if TYPE_CHECKING:
    from fastapi import FastAPI

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only; a hardcoded string
# here would silently fall behind it.
_VERSION = importlib.metadata.version(constants.DISTRIBUTION)


class RecordsModule(SubmissionHooks, ModuleBase):
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
        # Runtime state for the two framework hooks that describe types,
        # which are created after boot: each tenant's sidebar types
        # (:mod:`sm_records.menu`) and the role editor's per-type permissions
        # (:mod:`sm_records.type_permissions`). The module instance is the one
        # thing that outlives both the registries and the requests.
        from sm_records.menu import TypeMenuCache
        from sm_records.type_permissions import TypePermissions

        self.menu_cache = TypeMenuCache()
        self.type_permissions = TypePermissions()

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
        """Three static permissions, plus one per type from a runtime source.

        Types are created at runtime, after this hook, so their
        ``records.type.<key>`` permissions come from
        ``PermissionRegistry.add_source`` (framework 0.0.36, upstream #334) over
        a cache :mod:`sm_records.type_permissions` keeps. Design doc §10.
        """
        registry.add_group(
            constants.PERM_GROUP,
            [constants.PERM_VIEW, constants.PERM_EDIT, constants.PERM_MANAGE_TYPES],
        )
        self.type_permissions.register(registry)

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
        # A type opting into its own entry (``show_in_menu``) is a runtime
        # fact, and each tenant has its own: a per-request provider (framework
        # 0.0.36, upstream #340) reads the request's tenant's types.
        from sm_records.menu import type_menu_provider

        registry.add_provider(lambda request: type_menu_provider(self, request))

    def mark_menu_dirty(self) -> None:
        """Re-read the sidebar types and the per-type permissions on the next
        request that needs them.

        Called through :func:`sm_records.menu.mark_dirty` by the endpoints
        that write a type. It drops and flags rather than reads: the write has
        not committed yet when they call it (the framework commits after the
        response starts), so reading now would read the row as it was.
        """
        self.menu_cache.clear()
        self.type_permissions.mark_dirty()

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
        is fixed, so they are exempted here, for ``GET`` and ``POST`` only —
        and the newsletter's landing pages for ``GET`` only.
        """
        registry.add_prefix(
            constants.PUBLIC_SUBMISSIONS_API_PREFIX,
            methods=set(constants.PUBLIC_SUBMISSIONS_ROUTE_METHODS),
        )
        registry.add_prefix(constants.PUBLIC_SUBMISSIONS_VIEW_PREFIX, methods={"GET"})

    def register_middleware(self, app: FastAPI) -> None:
        """Install the deferred-job drain and the per-type permission sync.

        The drain is :mod:`sm_records.deferred`: the reindex of §8.9 must not
        start until the request that scheduled it has committed and released
        its session, and middleware is the first hook that runs after a
        route's dependency teardown. A ``BackgroundTasks`` entry runs *inside*
        it, which on SQLite deadlocks the schema write against its own
        rebuild.

        The sync is :mod:`sm_records.type_permissions`, and middleware for a
        different reason — see below.

        The body guard is :mod:`sm_records._body_limit`, and middleware
        because a router dependency runs *after* FastAPI has read and parsed
        the body for the endpoint's model — which is the cost it exists to
        avoid. The framework offers nothing shared to hook into here.
        """
        from sm_records._body_limit import BodyLimitMiddleware
        from sm_records._permission_sync import PermissionSyncMiddleware
        from sm_records.deferred import DeferredJobsMiddleware

        app.add_middleware(DeferredJobsMiddleware)
        # Added before the two below so it ends up *outside* them
        # (``add_middleware`` is LIFO): a body this module will not read must
        # not have a permission sync or a deferred-job drain wrapped around it.
        app.add_middleware(BodyLimitMiddleware)
        # Parked before the middleware that reads it so a handler can reach
        # this instance through ``request.app`` — today only to mark the
        # sidebar and the per-type permissions stale after a type write
        # (:func:`sm_records.menu.mark_dirty`).
        setattr(app.state, constants.MODULE_ATTR, self)
        # Keeps the role editor's per-type permissions current in *this*
        # worker: the framework's source is sync and cannot read, so the read
        # happens here, before the route — see :mod:`sm_records._permission_sync`.
        app.add_middleware(PermissionSyncMiddleware, module=self)

    async def on_startup(self, app: FastAPI) -> None:
        """Everything that needs the hydrated settings and an open database —
        the tenancy guard, the anonymous read API, the media picker, the
        orphaned-locale count and the first sidebar read. The body is
        :func:`sm_records.boot.startup`, which says why each runs here."""
        from sm_records import boot

        await boot.startup(self, app)

    async def on_shutdown(self, app: FastAPI) -> None:
        """Stop the retention loop, let in-flight submission mail finish
        (bounded), then stop the pattern-check workers
        (``sm_records._pattern_worker``). Without the drain a send cancelled
        at shutdown leaves its claim to expire and the record "not sent"
        until someone presses *Resend*."""
        import asyncio
        import contextlib

        from sm_records import _pattern_worker
        from sm_records.public_submissions import retention_loop
        from sm_records.public_submissions.mail_runner import drain

        await retention_loop.stop(self)

        with contextlib.suppress(TimeoutError):
            await asyncio.wait_for(drain(), timeout=30)
        await _pattern_worker.close()

    def locale_dirs(self) -> dict[str, Path]:
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.PERM_GROUP: base}

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        # Imported here, not at module top: the entry point must resolve for
        # Alembic autogenerate and the doctor even when the routers cannot be
        # built yet, and a top-level import would make one missing dependency
        # take the whole module — and its tables — out of discovery.
        from sm_records.endpoints.api import router as api
        from sm_records.endpoints.api.public_submissions_links import router as links
        from sm_records.endpoints.api.public_submissions_public import router as submissions
        from sm_records.endpoints.views import router as views

        api_router.include_router(api)
        # Beside the admin router, not in it: anonymous, so without its tenant
        # binding and CSRF check (``endpoints.api.public_submissions_public``);
        # the newsletter's links bind the tenant their token names.
        prefix = constants.PUBLIC_SUBMISSIONS_API_PREFIX.removeprefix(constants.ROUTE_PREFIX_API)
        for router in (links, submissions):
            api_router.include_router(router, prefix=prefix.rstrip("/"))
        view_router.include_router(views)
