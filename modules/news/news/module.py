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

from fastapi import APIRouter
from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.menu import MenuItem, MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry

from news import constants

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
        registry.add(
            MenuItem(
                label="News",
                url=constants.MENU_URL,
                icon=constants.MENU_ICON,
                group=constants.MENU_GROUP,
            )
        )

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """Let the feed block list articles for an anonymous visitor.

        Reads only, and by exact prefix: the same paths carry POST/PUT/DELETE,
        which must stay behind ``news.edit``.
        """
        for prefix in constants.PUBLIC_READ_PREFIXES:
            registry.add_prefix(prefix, methods={"GET"})
