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

from pagebuilder import boot, locales
from pagebuilder.scheduler import Scheduler
from pagebuilder.settings import PagebuilderSettings

_log = logging.getLogger("simple_module.pagebuilder")

# Sidebar entries. Grouped under "Content" so an app that installs several
# content modules clusters them together rather than scattering them.
# Paired with the news module's own group: the rail reads News / Site, so a
# screen's section is visible before you click it.
_PACKAGE = "pagebuilder"
#: The prefix every key in ``pagebuilder/locales/*.json`` is registered under,
#: so a console string is ``pagebuilder.<section>.<key>``. Deliberately the
#: package name: the frontend derives the same prefix in
#: ``pagebuilder/utils/i18n.ts``, and the two have to agree or every label in
#: the editor renders as its own key.
_LOCALE_NAMESPACE = _PACKAGE
#: The framework's settings module, by ``ModuleMeta.name``. Depending on it is
#: what guarantees ``app.state.settings.module_registry`` exists by the time
#: ``register_settings`` runs — the host topo-sorts modules on this field.
_MODULE_SETTINGS = "Settings"

_MENU_GROUP = "Site"
_URL_PAGES = "/pagebuilder/"
_URL_LAYOUT = "/pagebuilder/layout"
_URL_MEDIA = "/pagebuilder/media"
_URL_CONTENT = "/pagebuilder/content"
_ICON_PAGES = "file-text"
_ICON_LAYOUT = "layout"
_ICON_MEDIA = "image"
_ICON_CONTENT = "package"


# Read from installed package metadata so pyproject.toml is the single source
# of truth. The lockstep release bump edits pyproject only; a hardcoded string
# here would silently fall behind it.
_VERSION = importlib.metadata.version("simple_module_pagebuilder")


class PagebuilderModule(ModuleBase):
    meta = ModuleMeta(
        name="PageBuilder",
        route_prefix="/api/pagebuilder",
        view_prefix="/pagebuilder",
        depends_on=[_MODULE_SETTINGS],
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
        self.settings: PagebuilderSettings | None = None
        self._scheduler = Scheduler()

    def _live_settings(self, app: FastAPI) -> PagebuilderSettings:
        """The settings the app is actually running on.

        Read off ``app.state.pagebuilder`` rather than ``self``: the host's
        hydrate step assigns the DB-resolved instance *there*, so the copy the
        module handed over during ``register_settings`` is the pre-hydration
        one. Anything called after lifespan start has to ask the container.
        """
        services = getattr(app.state, _PACKAGE, None)
        settings = getattr(services, "settings", None)
        if settings is None:  # pragma: no cover - register_settings always runs
            settings = self.settings or PagebuilderSettings()
        # Published process-wide here because the model's column default and
        # the public-URL builders are pure functions with no request to read
        # ``app.state`` from.
        locales.use(settings)
        return settings

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """Nothing here — the exemptions are added at startup instead.

        Which paths are public depends on ``content_locales``,
        ``public_route_prefix`` and the two SEO switches, and this hook runs
        during app construction, before the host hydrates those from the
        database. Exempting the defaults here would open ``/p/`` on a site
        whose pages live at ``/pages/`` and leave ``/de/p/`` behind a login.

        ``AuthMiddleware`` reads the registry live, so :func:`boot.
        exempt_public_routes` can fill it from ``on_startup`` — after
        hydration, before the first request.
        """
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
                MenuItem(
                    label="Import / Export",
                    url=_URL_CONTENT,
                    icon=_ICON_CONTENT,
                    order=230,
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

        # No settings read here on purpose. Routers are built during app
        # construction, before the host hydrates settings from the DB, so a
        # flag baked in now would be the pydantic default forever — the
        # Settings screen would offer a switch the running app never sees.
        # Both dependencies consult ``app.state.pagebuilder.settings`` per
        # request instead.
        api_router.include_router(api, dependencies=build_admin_dependencies())
        view_router.include_router(views, dependencies=build_view_dependencies())

    async def on_startup(self, app: FastAPI) -> None:
        """Wire the public surface, now that the settings are the real ones.

        Everything here reads configuration the host has just hydrated from
        the database — the languages the site publishes in, where pages serve,
        where media is mounted. See :mod:`pagebuilder.boot` for why this is
        late rather than during app construction.
        """
        settings = self._live_settings(app)
        boot.exempt_public_routes(app, settings)
        boot.mount_public_routers(app, settings)
        await boot.mount_media(app, settings)

        if settings.scheduler_enabled:
            self._scheduler.start(app, settings)

    def register_settings(self, app: FastAPI) -> None:
        """Register the settings class and mount the services container.

        ``register_module_settings`` records the class so the host can hydrate
        it from the DB at lifespan start — it assigns the result onto the
        container this creates, which is why every later read goes through
        ``app.state.pagebuilder`` rather than a captured local.

        The pre-seeded ``self.settings`` wins when present: that is the hook a
        test uses to pin configuration in a process with no settings rows.
        """
        from settings.registration import register_module_settings

        from pagebuilder.services import PagebuilderServices

        register_module_settings(
            app,
            _PACKAGE,
            PagebuilderSettings,
            lambda defaults: PagebuilderServices(settings=self.settings or defaults),
        )
        # Publish immediately as well as from ``on_startup``: the model's
        # ``locale`` column default is a pure function, and a row written
        # before the app ever starts (a CLI, a migration, a test) still has to
        # come out in the right language.
        locales.use(self.settings or PagebuilderSettings())

    def register_permissions(self, registry: PermissionRegistry) -> None:
        from pagebuilder.permissions import (
            ALL_PERMISSIONS,
            DEFAULT_ROLE_MAP,
        )

        registry.add_group("PageBuilder", list(ALL_PERMISSIONS))
        for role, perms in DEFAULT_ROLE_MAP.items():
            registry.map_role(role, perms)

    def register_middleware(self, app: FastAPI) -> None:
        """Install the CSRF cookie writer.

        Unconditionally, and without reading ``csrf_protect`` here: middleware
        is installed while the app is built, before the host hydrates settings
        from the database. The middleware checks the flag itself on each
        request and passes straight through when CSRF is off, so installing it
        always costs a dictionary lookup rather than a wrong answer.
        """
        from pagebuilder.security import CsrfCookieMiddleware

        app.add_middleware(
            CsrfCookieMiddleware,
            admin_prefixes=(self.meta.route_prefix, self.meta.view_prefix),
        )

    def locale_dirs(self) -> dict[str, Path]:
        """Where the editor's own strings live, for the host's i18n registry.

        ``importlib.resources.files`` rather than ``__file__``: the JSON ships
        inside the wheel, so a host that pip-installed pagebuilder has to
        resolve it through the package rather than off a source tree that isn't
        there.

        The directory sits beside :mod:`pagebuilder.locales`, which is a
        different thing entirely — that one is the languages a *page* can be
        authored in, this one is the language the *editor* speaks. They coexist
        because the directory has no ``__init__.py``: an import of
        ``pagebuilder.locales`` resolves the module, and this joins the path
        without importing anything. Adding an ``__init__.py`` here would shadow
        the module and take the public viewer down with it.
        """
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {_LOCALE_NAMESPACE: base}

    def static_mounts(self) -> dict[str, Path]:
        pkg_root = Path(str(importlib.resources.files("pagebuilder")))
        dist = pkg_root / "static" / "dist"
        if not dist.is_dir():
            return {}
        return {"/modules/pagebuilder/static": dist}
