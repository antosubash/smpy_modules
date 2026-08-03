"""Module registration: routes, permissions, menu and the anonymous read surface.

The ``build_test_app`` and ``fake_event_bus`` fixtures come from the
``simple_module_test`` pytest plugin (registered via entry_points when
that package is installed). No conftest.py is required.
"""

from __future__ import annotations

import inspect

from news import constants
from news.endpoints import views
from news.module import NewsModule
from simple_module_core.menu import MenuRegistry
from simple_module_core.permissions import PermissionRegistry
from simple_module_core.public_routes import PublicRouteRegistry


class TestMeta:
    def test_meta_name(self):
        assert NewsModule.meta.name == "News"

    def test_meta_requires_framework(self):
        assert NewsModule.meta.requires_framework is not None

    def test_depends_on_pagebuilder(self):
        # An article's body, slug and public URL all live in a page, so the
        # host must boot pagebuilder first.
        assert constants._MODULE_PAGEBUILDER in NewsModule.meta.depends_on


class TestRoutes:
    async def test_app_boots_with_module(self, build_test_app):
        """Module registers cleanly into a minimal FastAPI host.

        Read through the OpenAPI schema, not ``app.routes``: since FastAPI
        0.141 ``include_router`` records an ``_IncludedRouter`` instead of
        copying each route up, so ``app.routes`` lists none of them.
        """
        app = build_test_app(NewsModule)
        paths = set(app.openapi()["paths"])
        assert f"{constants.ROUTE_PREFIX_API}/articles" in paths
        assert f"{constants.ROUTE_PREFIX_API}/categories" in paths

    def test_page_constant_matches_view_literal(self):
        # Guards against the inlined render literal drifting from the constant
        # (the literal is required inline for SM003/SM004 static AST pairing).
        assert constants._PAGE_LIST in inspect.getsource(views)


class TestPermissions:
    def test_registers_view_and_edit(self):
        registry = PermissionRegistry()
        NewsModule().register_permissions(registry)
        assert {constants.PERM_VIEW, constants.PERM_EDIT} <= set(registry.all_permissions)


class TestMenu:
    def test_lists_under_content(self):
        registry = MenuRegistry()
        NewsModule().register_menu_items(registry)
        item = registry.all_items[0]
        assert item.url == constants.MENU_URL
        assert item.group == constants.MENU_GROUP

    def test_menu_url_ends_in_a_slash(self):
        # The list route is registered at "/" under the view prefix, so the
        # bare prefix costs a 307 on every navigation.
        assert constants.MENU_URL.endswith("/")

    def test_no_role_restriction(self):
        # Role filtering is a plain intersection with no admin bypass, so a
        # non-empty list would hide the entry from everyone outside it.
        registry = MenuRegistry()
        NewsModule().register_menu_items(registry)
        assert registry.all_items[0].roles == []


class TestPublicRoutes:
    def test_reads_are_anonymous(self):
        # The feed block runs on public pages, so a visitor with no session
        # has to be able to list articles.
        registry = PublicRouteRegistry()
        NewsModule().register_public_routes(registry)
        patterns = {route.pattern for route in registry.routes}
        assert set(constants.PUBLIC_READ_PREFIXES) <= patterns

    def test_writes_stay_behind_auth(self):
        # The same paths carry POST/PUT/DELETE. Exempting every method would
        # let an anonymous caller attach and edit articles.
        registry = PublicRouteRegistry()
        NewsModule().register_public_routes(registry)
        for route in registry.routes:
            assert route.methods == {"GET"}
