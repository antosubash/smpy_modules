"""News — articles backed by page-builder pages.

An article *is* a page: the body, slug, approval workflow and revisions all
belong to ``pagebuilder``. This module adds only the metadata a page has no
concept of — category and display date — plus the listing API and the feed
block that renders it.

The one thing it does own is the article's public *address*.
Articles used to share pagebuilder's generic page prefix, sitting at
``/p/{slug}`` alongside the contact page, so the URL said nothing about what
the document was. They serve at ``{NewsSettings.public_route_prefix}/{slug}``
now, and pagebuilder is told so — the page stops answering at ``/p`` and the
sitemap advertises the news address instead.

The *rendering* is still pagebuilder's: the news route resolves the slug and
hands off to its viewer, so the ETag, cache, CSP, canonical and site-layout
handling stay in one place rather than being duplicated and left to drift.
"""

from __future__ import annotations

import importlib.metadata
import logging
from dataclasses import dataclass

from fastapi import APIRouter, FastAPI
from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.events import EventBus
from simple_module_core.menu import MenuItem, MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from news import constants
from news import settings as news_settings
from news.integrations.pagebuilder import PageDeleted, claim_slugs
from news.settings import NewsSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _NewsServices:
    """Module-scoped state on ``app.state.news``, mirroring pagebuilder's."""

    settings: NewsSettings


def _dir_prefix(prefix: str) -> str:
    """Normalise a route prefix to end in exactly one "/"."""
    return f"{prefix.rstrip('/')}/"

_VERSION = importlib.metadata.version("simple_module_news")


class NewsModule(ModuleBase):
    meta = ModuleMeta(
        name="News",
        route_prefix=constants.ROUTE_PREFIX_API,
        view_prefix=constants.VIEW_PREFIX,
        depends_on=[constants._MODULE_PAGEBUILDER],
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) — this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def __init__(self) -> None:
        super().__init__()
        # ``register_settings`` runs before routes and public-route rules, and
        # populates this so every later hook reads one env-resolved instance —
        # and so a test can pre-seed an override.
        self.settings: NewsSettings | None = None

    def _resolved_settings(self) -> NewsSettings:
        if self.settings is None:
            self.settings = NewsSettings()
        return self.settings

    def register_settings(self, app: FastAPI) -> None:
        resolved = self._resolved_settings()
        app.state.news = _NewsServices(settings=resolved)
        # Also published process-wide: the article serializer builds the
        # public URL and has no request to read app.state from.
        news_settings.use(resolved)

    def register_routes(self, api_router: APIRouter, view_router: APIRouter) -> None:
        from news.endpoints.api import router as api
        from news.endpoints.views import router as views

        api_router.include_router(api)
        view_router.include_router(views)

    def register_permissions(self, registry: PermissionRegistry) -> None:
        registry.add_group(
            NewsModule.meta.name, [constants.PERM_VIEW, constants.PERM_EDIT]
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
                # Its own group: the screen searches pages and media as well,
                # so listing it under News would say something untrue about
                # what it covers.
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
        """Drop an article when its page is deleted.

        This is not tidiness. There is no cross-module foreign key to cascade
        from, and a leftover row does not merely dangle: SQLite reuses the
        deleted page's id, so the article silently re-attaches to whatever page
        is created next and the listing shows one article's title under
        another's metadata.

        This is the fast path, not a guarantee — the bus logs a handler failure
        rather than raising it, and pagebuilder has already committed the page
        deletion by the time we run. ``on_startup``'s sweep is what makes the
        outcome eventual rather than merely likely.
        """
        if app is None:
            return

        async def _drop_article(event: PageDeleted) -> None:
            from news import service

            # Outside a request, so `get_db` is not managing this session and
            # the commit is ours to make.
            async with app.state.sm.db.session_factory() as db:
                article = await service.get_by_page(db, event.page_id)
                if article is not None:
                    await service.delete(db, article)
                    await db.commit()

        bus.subscribe(PageDeleted, _drop_article)

    async def on_startup(self, app: FastAPI) -> None:
        """Sweep away articles whose page no longer exists.

        Closes the window the ``PageDeleted`` subscription cannot: if that
        handler ever fails, the row survives with nothing to retry it, and the
        only trace is a log line. A restart is a cheap, natural boundary at
        which to reconcile, and the sweep costs one indexed anti-join over a
        table holding one row per article.

        A non-zero count means an event was lost, so it is logged at warning —
        the repair should be visible, not silent.
        """
        from news import service
        from news.endpoints.public_views import public_router, slug_claim
        from news.endpoints.views import admin_router

        # Mounted here rather than through ``register_routes`` because that
        # router is hard-prefixed with ``view_prefix``; this screen belongs at
        # the app root, for the same reason pagebuilder's public viewer does.
        app.include_router(admin_router, prefix=constants.ADMIN_SEARCH_PREFIX)

        # The public viewer, mounted at the app root for the same reason and
        # claimed with pagebuilder in the same breath: the prefix an article is
        # served at and the prefix a crawler is sent to are one value, so they
        # cannot drift apart.
        prefix = self._resolved_settings().public_route_prefix
        app.include_router(public_router, prefix=prefix)
        claim_slugs(slug_claim())

        async with app.state.sm.db.session_factory() as db:
            dropped = await service.reconcile_orphans(db)
            await db.commit()
        if dropped:
            logger.warning(
                "Dropped %d orphaned news article(s) whose page no longer exists; "
                "a PageDeleted event was missed.",
                dropped,
            )

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """Let an anonymous visitor read an article, and the feed block list them.

        Reads only, and by exact prefix: the same API paths carry
        POST/PUT/DELETE, which must stay behind ``news.edit``.
        """
        for prefix in constants.PUBLIC_READ_PREFIXES:
            registry.add_prefix(prefix, methods={"GET"})
        # The public article viewer. Without this every article 302s an
        # anonymous reader to the login screen, which is the whole point of a
        # public address. The trailing slash is load-bearing — these are
        # ``startswith`` prefixes, so a bare "/news" would also exempt anything
        # that merely starts with those characters.
        registry.add_prefix(
            _dir_prefix(self._resolved_settings().public_route_prefix),
            methods={"GET", "HEAD"},
        )
