"""PageBuilder module — drag-and-drop visual page builder."""

from __future__ import annotations

import asyncio
import contextlib
import importlib.metadata
import importlib.resources
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, FastAPI
from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from pagebuilder.media_files import MediaFiles, resolve_media_root, warn_on_orphaned_media
from pagebuilder.settings import PagebuilderSettings

_scheduler_log = logging.getLogger("simple_module.pagebuilder.scheduler")
_log = logging.getLogger("simple_module.pagebuilder")

# Sidebar entries. Grouped under "Content" so an app that installs several
# content modules clusters them together rather than scattering them.
# Paired with the news module's own group: the rail reads News / Site, so a
# screen's section is visible before you click it.
_MENU_GROUP = "Site"
_URL_PAGES = "/pagebuilder/"
_URL_LAYOUT = "/pagebuilder/layout"
_URL_MEDIA = "/pagebuilder/media"
_ICON_PAGES = "file-text"
_ICON_LAYOUT = "layout"
_ICON_MEDIA = "image"


def _dir_prefix(prefix: str) -> str:
    """Normalise a route prefix to end in exactly one "/".

    Public-route rules match with ``str.startswith``, so an unterminated
    prefix leaks into sibling paths that merely share its first characters.
    """
    return f"{prefix.rstrip('/')}/"

# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only; a hardcoded string
# here would silently fall behind it.
_VERSION = importlib.metadata.version("simple_module_pagebuilder")


class PagebuilderModule(ModuleBase):
    meta = ModuleMeta(
        name="PageBuilder",
        route_prefix="/api/pagebuilder",
        view_prefix="/pagebuilder",
        depends_on=[],
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) — this range is correct as written.
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

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """Exempt the reader-facing surface from authentication.

        Without this the whole point of the module is defeated: ``AuthMiddleware``
        gates every request, so a published page, the sitemap, and robots.txt all
        302 an anonymous visitor to the login screen.

        GET/HEAD only — the admin API lives under a different prefix, but pinning
        the verbs keeps the exemption from widening if a future route adds a POST
        under one of these paths.
        """
        settings = self._resolved_settings()
        read_only = {"GET", "HEAD"}
        # Trailing slash is load-bearing. These are startswith() prefixes, so a
        # bare "/p" would also exempt "/pagebuilder/" — the entire admin surface.
        registry.add_prefix(_dir_prefix(settings.public_route_prefix), methods=read_only)
        # Published pages reference uploaded images; without this the page
        # renders for an anonymous visitor but every image 302s to login.
        registry.add_prefix(_dir_prefix(settings.media_url_prefix), methods=read_only)
        if settings.sitemap_enabled:
            registry.add_exact("/sitemap.xml", methods=read_only)
        if settings.robots_enabled:
            registry.add_exact("/robots.txt", methods=read_only)

    def register_menu_items(self, registry: MenuRegistry) -> None:
        """Contribute the admin surface to the host's sidebar.

        Deliberately not role-gated. Menu role filtering is a plain
        intersection with no admin bypass, so listing the pagebuilder roles
        here would hide the entries from an ``admin`` user. It would also
        misrepresent the gating: these views require authentication only —
        it's the write endpoints that carry per-permission dependencies — so
        every authenticated user can reach them.
        """
        registry.add_many(
            [
                MenuItem(
                    label="Pages",
                    url=_URL_PAGES,
                    icon=_ICON_PAGES,
                    order=200,
                    section=MenuSection.SIDEBAR,
                    group=_MENU_GROUP,
                ),
                MenuItem(
                    label="Site layout",
                    url=_URL_LAYOUT,
                    icon=_ICON_LAYOUT,
                    order=210,
                    section=MenuSection.SIDEBAR,
                    group=_MENU_GROUP,
                ),
                MenuItem(
                    label="Media library",
                    url=_URL_MEDIA,
                    icon=_ICON_MEDIA,
                    order=220,
                    section=MenuSection.SIDEBAR,
                    group=_MENU_GROUP,
                ),
            ]
        )

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

        media_root = resolve_media_root(settings.media_root)
        media_root.mkdir(parents=True, exist_ok=True)
        _log.info("pagebuilder.media_root: %s", media_root)
        app.mount(
            settings.media_url_prefix,
            MediaFiles(directory=media_root),
            name="pagebuilder_media",
        )
        sm = getattr(app.state, "sm", None)
        if sm is not None:
            await warn_on_orphaned_media(sm.db.session_factory, media_root)

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
                        service = PagesService(session)
                        flipped = await service.process_due(datetime.now(UTC))
                        # The trash promises to empty itself after the retention
                        # window. Swept on the same tick as the flips rather than
                        # only at startup, so the promise holds for a process that
                        # stays up for months as well as one that restarts nightly.
                        purged = await service.purge_expired()
                        if flipped or purged:
                            await session.commit()
                            _scheduler_log.info(
                                "pagebuilder.scheduler.flipped",
                                extra={"count": len(flipped), "purged": purged},
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
