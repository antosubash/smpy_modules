"""News — a self-contained archive of articles.

An article used to *be* a pagebuilder page: the body, the slug, the workflow,
the revisions and the public rendering all belonged to that module, and this one
added a category and a date beside it. That made ``simple_module_news``
uninstallable without its neighbour, made every listing a cross-module join, and
left article rows that could be orphaned by a deletion news never saw.

It owns its content now. ``NewsArticle`` carries the body, the address, the
status and the SEO; :mod:`news.content` performs the writes;
:mod:`news.endpoints.public` serves the reader. Pagebuilder is optional —
where a host runs it, the admin search screen gains a Pages and a Media section,
the feed block joins its palette, and the site's content languages are its.
Where a host does not, news publishes in one language and nothing here notices.
See :mod:`news.integrations.pagebuilder`.

Everything this module reads *while booting* — where the viewer mounts, which
languages it mounts for, whether the scheduler runs — is read in
:meth:`NewsModule.on_startup`, never during app construction. The host hydrates
module settings from the database at lifespan start, so a value read earlier is
the pydantic default no matter what an operator has configured.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
import logging
from dataclasses import dataclass
from pathlib import Path

from fastapi import APIRouter, FastAPI
from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.events import EventBus
from simple_module_core.menu import MenuItem, MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from news import boot, constants, locales
from news import settings as news_settings
from news.scheduler import Scheduler
from news.settings import NewsSettings

logger = logging.getLogger(__name__)


@dataclass
class _NewsServices:
    """Module-scoped state on ``app.state.news``.

    Not frozen: the host's hydrate step assigns the DB-resolved settings onto
    this object at lifespan start, and the Settings screen assigns again on
    every save.
    """

    settings: NewsSettings


_VERSION = importlib.metadata.version("simple_module_news")


class NewsModule(ModuleBase):
    meta = ModuleMeta(
        name="News",
        route_prefix=constants.ROUTE_PREFIX_API,
        view_prefix=constants.VIEW_PREFIX,
        # "PageBuilder" is deliberately absent. That entry was here for as long
        # as an article was a page; this module now boots, migrates and serves
        # entirely on its own, and the neighbour is an optional extra. Settings
        # *is* depended on, so the host has built its module registry before
        # ``register_settings`` tries to register against it.
        depends_on=[constants._MODULE_SETTINGS],
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) — this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def __init__(self) -> None:
        super().__init__()
        # Pre-seeding this pins the settings for a test with no database behind
        # it: ``register_settings`` hands it to the services container in place
        # of the pydantic defaults, and nothing overwrites it.
        self.settings: NewsSettings | None = None
        self._scheduler = Scheduler()

    def register_settings(self, app: FastAPI) -> None:
        """Register the settings class; the host hydrates it from the DB.

        ``register_module_settings`` records the class so the host can hydrate
        it at lifespan start — it assigns the result onto the container this
        creates, which is why every later read goes through ``app.state.news``
        rather than a captured local.
        """
        from settings.registration import register_module_settings

        register_module_settings(
            app,
            constants.PACKAGE,
            NewsSettings,
            lambda defaults: _NewsServices(settings=self.settings or defaults),
        )
        # Published immediately as well as from ``on_startup``: the article
        # serializer builds the public URL from a pure function, and a row
        # written before the app ever starts — a CLI, a migration, a test —
        # still has to come out with the right address.
        news_settings.use(self.settings or NewsSettings())

    def _live_settings(self, app: FastAPI) -> NewsSettings:
        """The settings the app is actually running on.

        Off ``app.state.news``, because that is where the host's hydrate step
        puts the DB-resolved instance — the one handed over during
        ``register_settings`` predates it.
        """
        services = getattr(app.state, constants.PACKAGE, None)
        settings = getattr(services, "settings", None)
        if settings is None:  # pragma: no cover - register_settings always runs
            settings = self.settings or NewsSettings()
        # Republished process-wide: the article serializer builds the public
        # URL and has no request to read app.state from.
        news_settings.use(settings)
        return settings

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from news.endpoints.api import router as api
        from news.endpoints.views import router as views

        api_router.include_router(api)
        view_router.include_router(views)

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(
            NewsModule.meta.name,
            [constants.PERM_VIEW, constants.PERM_EDIT, constants.PERM_PUBLISH],
        )

    def register_menu_items(self, registry: MenuRegistry) -> None:
        # Roles stay empty: filtering is a plain intersection with no admin
        # bypass, so a non-empty list hides the entry from everyone outside it.
        registry.add_many(
            [
                MenuItem(
                    label=constants.MENU_LABEL_ARTICLES,
                    url=constants.MENU_URL,
                    icon=constants.MENU_ICON,
                    order=100,
                    group=constants.MENU_GROUP,
                ),
                MenuItem(
                    label=constants.MENU_LABEL_CATEGORIES,
                    url=constants.MENU_URL_CATEGORIES,
                    icon=constants.MENU_ICON_CATEGORIES,
                    order=110,
                    group=constants.MENU_GROUP,
                ),
                # In the rail rather than behind a filter on the list: a trashed
                # article keeps its slug claimed, so an author who bins one and
                # cannot find it tries to recreate it and is told the URL is
                # taken by something they cannot see.
                MenuItem(
                    label=constants.MENU_LABEL_TRASH,
                    url=constants.MENU_URL_TRASH,
                    icon=constants.MENU_ICON_TRASH,
                    order=120,
                    group=constants.MENU_GROUP,
                ),
                # Its own group: where pagebuilder is installed the screen
                # searches pages and media as well, so listing it under News
                # would say something untrue about what it covers.
                MenuItem(
                    label=constants.MENU_LABEL_SEARCH,
                    url=constants.ADMIN_SEARCH_URL,
                    icon=constants.MENU_ICON_SEARCH,
                    order=10,
                    group=constants.MENU_GROUP_SEARCH,
                ),
            ]
        )

    def register_event_handlers(self, bus: EventBus, app: FastAPI | None = None) -> None:
        """Re-publish the settings when an operator saves them.

        Everything this module reads per request goes through
        ``news.settings.active()`` — a process-global, because the article
        serializer is a pure function with no request to read ``app.state``
        from. The Settings screen assigns the new instance onto the services
        container and publishes this event; without picking it up, that global
        would keep answering with whatever boot resolved, and every field not
        marked ``requires_restart`` would silently need one after all.
        """
        if app is None:
            return

        from settings.contracts.events import SettingsReloaded

        async def _republish(event: SettingsReloaded) -> None:
            if event.package == constants.PACKAGE:
                self._live_settings(app)

        bus.subscribe(SettingsReloaded, _republish)

    async def on_startup(self, app: FastAPI) -> None:
        """Mount everything that depends on a hydrated setting.

        This hook used to also sweep away articles whose page had been deleted,
        and subscribe to a ``PageDeleted`` event to catch the same thing sooner.
        Neither exists any more: an article's body is its own row, so there is
        no foreign row whose disappearance could orphan it, and nothing to
        reconcile after the fact.
        """
        from news.endpoints.views import admin_router

        # Which languages this site publishes in, before anything reads them.
        boot.publish_locales(app)

        # Mounted here rather than through ``register_routes`` because that
        # router is hard-prefixed with ``view_prefix``; this screen spans more
        # than the news console and belongs at the app root.
        app.include_router(admin_router, prefix=constants.ADMIN_SEARCH_PREFIX)

        # The public viewer and the archive, at the address articles serve on.
        settings = self._live_settings(app)
        prefix = settings.public_route_prefix
        boot.mount_public_routers(app, prefix)
        self._exempt_public_routes(app, prefix, locales.supported())

        if settings.scheduler_enabled:
            self._scheduler.start(app, settings)

    async def on_shutdown(self, app: FastAPI) -> None:
        """Stop the scheduler's polling task.

        Not reached through a FastAPI ``shutdown`` event handler — the host
        builds the app with a custom ``lifespan=``, which bypasses the
        router's own event-handler list entirely. This hook is what the
        host's lifespan actually calls on the way down, for every module, in
        reverse start order.
        """
        await self._scheduler.stop()

    def locale_dirs(self) -> dict[str, Path]:
        """Where the console's own strings live, for the host's i18n registry.

        ``importlib.resources.files`` rather than ``__file__``: the JSON ships
        inside the wheel, so a host that pip-installed news has to resolve it
        through the package rather than off a source tree that isn't there.

        The directory sits beside :mod:`news.locales`, which is a different
        thing entirely — that one is the languages an *article* can be written
        in, this one is the language the *console* speaks. They coexist because
        the directory has no ``__init__.py``: an import of ``news.locales``
        resolves the module, and this joins the path without importing
        anything. Adding an ``__init__.py`` here would shadow the module and
        take the public router down with it.
        """
        base = Path(str(importlib.resources.files(__package__) / "locales"))
        return {constants.LOCALE_NAMESPACE: base}

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """Let an anonymous reader use the API the feed block reads.

        Reads only, and by exact prefix: the same API paths carry
        POST/PUT/DELETE, which must stay behind ``news.edit``.

        The *viewer's* prefixes are not here. They depend on
        ``public_route_prefix`` and on the site's content languages, neither of
        which the host has hydrated from the database at this point in boot — so
        they are added from ``on_startup`` instead, into the same registry,
        which ``AuthMiddleware`` reads live.
        """
        for prefix in constants.PUBLIC_READ_PREFIXES:
            registry.add_prefix(prefix, methods={"GET"})

    def _exempt_public_routes(
        self, app: FastAPI, prefix: str, languages: tuple[str, ...]
    ) -> None:
        """Exempt the public article viewer from auth, one prefix per language.

        A method rather than a straight call to :mod:`news.boot` because it is
        the one piece of boot wiring that has to be exercisable on its own: what
        it exempts, and what it must *not*, is a security boundary with a test
        of its own.
        """
        boot.exempt_public_routes(app, prefix, languages)
