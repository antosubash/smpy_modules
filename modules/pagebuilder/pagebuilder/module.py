"""PageBuilder module — drag-and-drop visual page builder."""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import logging
from pathlib import Path

from fastapi import APIRouter, FastAPI
from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.menu import MenuItem, MenuRegistry, MenuSection
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from pagebuilder import locales
from pagebuilder.media_files import MediaFiles, resolve_media_root, warn_on_orphaned_media
from pagebuilder.scheduler import Scheduler
from pagebuilder.settings import PagebuilderSettings

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
        self._scheduler = Scheduler()

    def _resolved_settings(self) -> PagebuilderSettings:
        if self.settings is None:
            self.settings = PagebuilderSettings()
        # Published process-wide here rather than only from
        # ``register_settings``: the model's column default and the public-URL
        # builders are pure functions with no request to read ``app.state``
        # from, and ``register_public_routes`` needs the locale list too. This
        # is the one place settings are resolved, so hanging it here is what
        # makes "the module knows its languages" true from the first hook that
        # asks, in production and in a test that wires only some of them.
        locales.use(self.settings)
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
        #
        # One exemption per content locale, matching the mounts in
        # ``on_startup``. Exempting a bare "/{locale}" instead would be shorter
        # and wrong: it would open every path that happens to start with a
        # language tag, admin screens included.
        for locale in settings.content_locales:
            registry.add_prefix(
                _dir_prefix(
                    f"{locales.path_prefix(locale)}{settings.public_route_prefix}"
                ),
                methods=read_only,
            )
        if len(settings.content_locales) > 1:
            # The default locale's redundant prefix, which 301s to the bare
            # address (see ``default_locale_alias_router``). Exempt too, or the
            # redirect that exists to be forgiving answers with a login page.
            registry.add_prefix(
                _dir_prefix(
                    f"/{settings.default_content_locale}"
                    f"{settings.public_route_prefix}"
                ),
                methods=read_only,
            )
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
        the app once boot has finished. One mount per content locale: the
        default language at ``{public_route_prefix}/{slug}`` and every other
        at ``/{locale}{public_route_prefix}/{slug}``. The media directory is also
        mounted here so uploaded files are served from
        ``{media_url_prefix}/{filename}``. The ``/sitemap.xml`` +
        ``/robots.txt`` routes are mounted at the root so crawlers find
        them at the conventional location.
        """
        from pagebuilder.endpoints.public_views import (
            default_locale_alias_router,
            locale_router,
        )
        from pagebuilder.endpoints.seo import seo_router

        settings = self._resolved_settings()
        for locale in settings.content_locales:
            # The default language keeps the bare prefix so no address that
            # already exists changes; every other one is prefixed with its tag.
            app.include_router(
                locale_router(locale),
                prefix=f"{locales.path_prefix(locale)}{settings.public_route_prefix}",
            )
        if len(settings.content_locales) > 1:
            # Only worth mounting on a multilingual site: with one language
            # there is no /de/p/… for anyone to generalise from, so /en/p/…
            # is just a URL nobody types.
            app.include_router(
                default_locale_alias_router(settings),
                prefix=(
                    f"/{settings.default_content_locale}"
                    f"{settings.public_route_prefix}"
                ),
            )
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
            self._scheduler.start(app, settings)


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
