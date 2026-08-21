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

    def test_view_renders_the_page_the_constant_names(self):
        # The TSX file's path is what defines the page name, so a rename that
        # misses one side is a 404 the type system cannot see. The view reads
        # the constant, so this pins the constant to the file that must exist.
        assert f"{NewsModule.meta.name}/NewsList" == constants._PAGE_LIST
        assert "constants._PAGE_LIST" in inspect.getsource(views)


class TestPermissions:
    def test_registers_view_and_edit(self):
        registry = PermissionRegistry()
        NewsModule().register_permissions(registry)
        assert {constants.PERM_VIEW, constants.PERM_EDIT} <= set(registry.all_permissions)


class TestMenu:
    def test_lists_under_content(self):
        registry = MenuRegistry()
        NewsModule().register_menu_items(registry)
        # Found by URL rather than by position: the module registers three
        # entries across two groups now, and the registry orders them by
        # `order`, not by registration.
        item = next(i for i in registry.all_items if i.url == constants.MENU_URL)
        assert item.group == constants.MENU_GROUP

    def test_search_sits_outside_the_news_group(self):
        """It searches pages and media too, so filing it under News would say
        something untrue about what it covers."""
        registry = MenuRegistry()
        NewsModule().register_menu_items(registry)
        item = next(
            i for i in registry.all_items if i.url == constants.ADMIN_SEARCH_URL
        )
        assert item.group != constants.MENU_GROUP

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
        # The same API paths carry POST/PUT/DELETE. Exempting every method would
        # let an anonymous caller attach and edit articles. HEAD rides with GET
        # because the public article viewer answers it — a crawler's cheap
        # freshness check, and it reads nothing GET does not.
        registry = PublicRouteRegistry()
        NewsModule().register_public_routes(registry)
        for route in registry.routes:
            assert route.methods <= {"GET", "HEAD"}

    def test_the_public_prefix_does_not_swallow_the_admin_console(self):
        """The reason the console lives at /admin/news rather than /news.

        Public-route rules match with ``str.startswith``, so a console sharing
        the reader-facing prefix would be exempted from authentication wholesale
        — every article list, every category rename, open to anyone. The two
        prefixes must not be prefixes of each other.
        """
        registry = PublicRouteRegistry()
        NewsModule().register_public_routes(registry)

        # Asked through the registry's own matcher rather than by re-deriving
        # the rule here, so this fails if the matching itself ever widens.
        for path in (
            f"{constants.VIEW_PREFIX}/",
            f"{constants.VIEW_PREFIX}/categories",
            f"{constants.VIEW_PREFIX}/articles/1/edit",
        ):
            for route in registry.routes:
                assert not route.matches("GET", path), (
                    f"{route.pattern!r} exempts the admin console at {path!r}"
                )

    def test_the_article_viewer_is_readable_without_a_session(self):
        """Otherwise every article 302s a reader to the login screen, which
        would make having a public address pointless."""
        registry = PublicRouteRegistry()
        module = NewsModule()
        module.register_public_routes(registry)

        prefix = module._resolved_settings().public_route_prefix
        assert any(
            route.matches("GET", f"{prefix}/some-article") for route in registry.routes
        )
