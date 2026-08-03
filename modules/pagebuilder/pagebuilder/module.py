"""PageBuilder module — drag-and-drop visual page builder."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.resources
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI
from fastapi.staticfiles import StaticFiles
from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.permissions import PermissionRegistry

from pagebuilder.settings import PagebuilderSettings

_scheduler_log = logging.getLogger("simple_module.pagebuilder.scheduler")


class PagebuilderModule(ModuleBase):
    meta = ModuleMeta(
        name="PageBuilder",
        route_prefix="/api/pagebuilder",
        view_prefix="/pagebuilder",
        depends_on=[],
        version="0.2.0",
        requires_framework=">=1.0,<2.0",
    )

    def __init__(self) -> None:
        super().__init__()
        # ``register_settings`` is called first by the host (phase 4),
        # before middleware (phase 8) and routes (phase 9). It populates
        # this so later hooks read a single env-resolved settings
        # instance — and so tests can pre-seed an override.
        self.settings: PagebuilderSettings | None = None
        self._scheduler_task: asyncio.Task[None] | None = None

    def _resolved_settings(self) -> PagebuilderSettings:
        if self.settings is None:
            self.settings = PagebuilderSettings()
        return self.settings

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from pagebuilder.endpoints.api import router as api
        from pagebuilder.endpoints.views import router as views
        from pagebuilder.security import (
            build_admin_dependencies,
            build_view_dependencies,
        )

        settings = self._resolved_settings()
        api_router.include_router(
            api,
            dependencies=build_admin_dependencies(
                requires_auth=settings.requires_auth,
                csrf_protect=settings.csrf_protect,
            ),
        )
        view_router.include_router(
            views,
            dependencies=build_view_dependencies(
                requires_auth=settings.requires_auth,
                csrf_protect=settings.csrf_protect,
            ),
        )

    async def on_startup(self, app: FastAPI) -> None:
        """Mount the public viewer + media directory at the host root.

        The host's view_router is hard-prefixed with ``view_prefix`` so
        the public viewer can't live there — we attach it directly to
        the app once boot has finished. The media directory is also
        mounted here so uploaded files are served from
        ``{media_url_prefix}/{filename}``. The ``/sitemap.xml`` +
        ``/robots.txt`` routes are mounted at the root so crawlers find
        them at the conventional location.
        """
        from pagebuilder.endpoints.seo import seo_router
        from pagebuilder.endpoints.views import public_router

        settings = self._resolved_settings()
        app.include_router(public_router, prefix=settings.public_route_prefix)
        if settings.sitemap_enabled or settings.robots_enabled:
            app.include_router(seo_router)

        media_root = Path(settings.media_root).resolve()
        media_root.mkdir(parents=True, exist_ok=True)
        app.mount(
            settings.media_url_prefix,
            StaticFiles(directory=media_root),
            name="pagebuilder_media",
        )

        if settings.scheduler_enabled:
            self._scheduler_task = asyncio.create_task(
                self._run_scheduler(app, settings)
            )
            # FastAPI 0.136 no longer exposes ``add_event_handler`` on the
            # app itself; the router still carries it for ASGI lifespan
            # hooks, which is what we want here — the task lives as long
            # as the app does and gets cancelled on shutdown.
            app.router.add_event_handler("shutdown", self._stop_scheduler)

    async def _run_scheduler(self, app: FastAPI, settings: PagebuilderSettings) -> None:
        """Poll for scheduled publish / unpublish flips.

        One DB session per tick — short, write-or-rollback. Errors on a
        single tick are logged and the loop continues; cancellation
        (shutdown) is propagated.
        """
        from pagebuilder.service import PagesService

        factory = app.state.sm.db.session_factory
        interval = max(1, settings.scheduler_interval_seconds)
        while True:
            try:
                await asyncio.sleep(interval)
                async with factory() as session:
                    try:
                        flipped = await PagesService(session).process_due(
                            datetime.now(UTC)
                        )
                        if flipped:
                            await session.commit()
                            _scheduler_log.info(
                                "pagebuilder.scheduler.flipped",
                                extra={"count": len(flipped)},
                            )
                        else:
                            await session.rollback()
                    except Exception:
                        await session.rollback()
                        raise
            except asyncio.CancelledError:
                raise
            except Exception:
                _scheduler_log.exception("pagebuilder.scheduler.tick_failed")

    async def _stop_scheduler(self) -> None:
        if self._scheduler_task is None:
            return
        self._scheduler_task.cancel()
        # CancelledError is listed explicitly because it derives from
        # BaseException, not Exception, so it isn't covered by the latter.
        with contextlib.suppress(asyncio.CancelledError, Exception):
            await self._scheduler_task
        self._scheduler_task = None

    def register_settings(self, app: FastAPI) -> None:
        from pagebuilder.services import PagebuilderServices

        settings = self._resolved_settings()
        app.state.pagebuilder = PagebuilderServices(settings=settings)

    def register_permissions(self, registry: PermissionRegistry) -> None:
        from pagebuilder.permissions import (
            ALL_PERMISSIONS,
            DEFAULT_ROLE_MAP,
        )

        registry.add_group("PageBuilder", list(ALL_PERMISSIONS))
        for role, perms in DEFAULT_ROLE_MAP.items():
            registry.map_role(role, perms)

    def register_middleware(self, app: FastAPI) -> None:
        from pagebuilder.security import CsrfCookieMiddleware

        settings = self._resolved_settings()
        if settings.csrf_protect:
            app.add_middleware(
                CsrfCookieMiddleware,
                cookie_name=settings.csrf_cookie_name,
                admin_prefixes=(
                    self.meta.route_prefix,
                    self.meta.view_prefix,
                ),
            )

    def static_mounts(self) -> dict[str, Path]:
        pkg_root = Path(str(importlib.resources.files("pagebuilder")))
        dist = pkg_root / "static" / "dist"
        if not dist.is_dir():
            return {}
        return {"/modules/pagebuilder/static": dist}
