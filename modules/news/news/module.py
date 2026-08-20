"""News — articles backed by page-builder pages.

An article *is* a page: the body, slug, approval workflow, revisions and public
URL all belong to ``pagebuilder``. This module adds only the metadata a page
has no concept of — category and display date — plus the listing API and the
feed block that renders it.

There is therefore no public route here. An article serves at ``/p/{slug}``
with the existing ETag, cache, CSP, SEO and site-layout handling; a second
viewer would mean duplicating all of it.
"""

from __future__ import annotations

import importlib.metadata
import logging

from fastapi import APIRouter, FastAPI
from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.events import EventBus
from simple_module_core.menu import MenuItem, MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from news import constants
from news.integrations.pagebuilder import PageDeleted

logger = logging.getLogger(__name__)

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
        from news.endpoints.views import admin_router

        # Mounted here rather than through ``register_routes`` because that
        # router is hard-prefixed with ``view_prefix``; this screen belongs at
        # the app root, for the same reason pagebuilder's public viewer does.
        app.include_router(admin_router, prefix=constants.ADMIN_SEARCH_PREFIX)

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
        """Let the feed block list articles for an anonymous visitor.

        Reads only, and by exact prefix: the same paths carry POST/PUT/DELETE,
        which must stay behind ``news.edit``.
        """
        for prefix in constants.PUBLIC_READ_PREFIXES:
            registry.add_prefix(prefix, methods={"GET"})
