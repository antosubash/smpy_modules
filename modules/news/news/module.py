"""News — a self-contained archive of articles.

An article used to *be* a pagebuilder page: the body, the slug, the workflow,
the revisions and the public rendering all belonged to that module, and this one
added a category and a date beside it. That made ``simple_module_news``
uninstallable without its neighbour, made every listing a cross-module join, and
left article rows that could be orphaned by a deletion news never saw.

It owns its content now. ``NewsArticle`` carries the body, the address, the
status and the SEO; :mod:`news.content` performs the writes;
:mod:`news.endpoints.public` serves the reader. Pagebuilder is optional —
where a host runs it, the admin search screen gains a Pages and a Media section
and the feed block joins its palette. Where a host does not, nothing here
notices. See :mod:`news.integrations.pagebuilder`.
"""

from __future__ import annotations

import asyncio
import importlib.metadata
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import APIRouter, FastAPI
from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.menu import MenuItem, MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from news import constants
from news import settings as news_settings
from news.settings import NewsSettings

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class _NewsServices:
    """Module-scoped state on ``app.state.news``."""

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
        # No ``depends_on``. That list held "PageBuilder" for as long as an
        # article was a page; it is empty because this module now boots,
        # migrates and serves entirely on its own.
        depends_on=[],
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

    async def on_startup(self, app: FastAPI) -> None:
        """Mount the two routers that do not belong under ``view_prefix``.

        This hook used to also sweep away articles whose page had been deleted,
        and subscribe to a ``PageDeleted`` event to catch the same thing sooner.
        Neither exists any more: an article's body is its own row, so there is
        no foreign row whose disappearance could orphan it, and nothing to
        reconcile after the fact.
        """
        from news.endpoints.public import public_router
        from news.endpoints.views import admin_router

        # Mounted here rather than through ``register_routes`` because that
        # router is hard-prefixed with ``view_prefix``; this screen spans more
        # than the news console and belongs at the app root.
        app.include_router(admin_router, prefix=constants.ADMIN_SEARCH_PREFIX)

        # The public viewer and the archive, at the address articles serve on.
        settings = self._resolved_settings()
        app.include_router(public_router, prefix=settings.public_route_prefix)

        if settings.scheduler_enabled:
            self._scheduler_task = asyncio.create_task(
                self._run_scheduler(app, settings)
            )
            # FastAPI no longer exposes ``add_event_handler`` on the app itself;
            # the router still carries it for ASGI lifespan hooks, which is what
            # this wants — the task lives as long as the app and is cancelled on
            # shutdown rather than outliving it.
            app.router.add_event_handler("shutdown", self._stop_scheduler)

    async def _run_scheduler(self, app: FastAPI, settings: NewsSettings) -> None:
        """Publish and unpublish articles at their scheduled times.

        One short session per tick. A failed tick is logged and the loop
        continues — a transient database error must not silently stop every
        future schedule — while cancellation propagates, because that is
        shutdown.
        """
        from news.content import ArticlesService

        factory = app.state.sm.db.session_factory
        interval = max(1, settings.scheduler_interval_seconds)
        while True:
            try:
                await asyncio.sleep(interval)
                async with factory() as session:
                    try:
                        flipped = await ArticlesService(session).process_due(
                            datetime.now(UTC)
                        )
                        if flipped:
                            await session.commit()
                            logger.info(
                                "news.scheduler.flipped",
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
                logger.exception("news.scheduler.tick_failed")

    async def _stop_scheduler(self) -> None:
        task = getattr(self, "_scheduler_task", None)
        if task is None:
            return
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task
        self._scheduler_task = None

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """Let an anonymous reader open an article, and the feed block list them.

        Reads only, and by exact prefix: the same API paths carry
        POST/PUT/DELETE, which must stay behind ``news.edit``.
        """
        for prefix in constants.PUBLIC_READ_PREFIXES:
            registry.add_prefix(prefix, methods={"GET"})
        # The public article viewer and its sitemap. Without this every article
        # 302s an anonymous reader to the login screen, which is the whole point
        # of a public address. The trailing slash is load-bearing — these are
        # ``startswith`` prefixes, so a bare "/news" would also exempt anything
        # that merely starts with those characters.
        prefix = self._resolved_settings().public_route_prefix
        registry.add_prefix(_dir_prefix(prefix), methods={"GET", "HEAD"})
        # And the bare prefix, exactly. A reader who trims the URL back to
        # "/news" is asking for the archive's front page; without this they got
        # the sign-in screen instead, because the prefix rule above only covers
        # "/news/" and the redirect to it never happens — auth runs before
        # routing. Exact rather than a second prefix on purpose: "/news" as a
        # prefix would also exempt "/newsletter-admin".
        registry.add_exact(prefix.rstrip("/"), methods={"GET", "HEAD"})
