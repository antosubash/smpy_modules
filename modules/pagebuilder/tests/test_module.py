"""Smoke tests for the PageBuilder module."""

from __future__ import annotations

import importlib.metadata

from pagebuilder.module import PagebuilderModule
from simple_module_core.menu import MenuRegistry, MenuSection


class TestMeta:
    def test_meta_name(self):
        assert PagebuilderModule.meta.name == "PageBuilder"

    def test_meta_requires_framework(self):
        assert PagebuilderModule.meta.requires_framework is not None

    def test_meta_version_tracks_package_metadata(self):
        """meta.version must not drift from pyproject.toml.

        The lockstep release bump edits pyproject only, so meta reads the
        installed distribution version rather than carrying its own literal.
        """
        assert PagebuilderModule.meta.version == importlib.metadata.version(
            "simple_module_pagebuilder"
        )


def _registered_paths(app) -> set[str]:
    """Enumerate a module's routes.

    Reads the OpenAPI schema rather than walking ``app.routes``. Since
    FastAPI 0.141, ``include_router`` no longer copies the sub-router's
    routes onto the parent — it wraps them in a single lazily-resolved
    ``_IncludedRouter`` with no ``path`` attribute, so walking
    ``app.routes`` finds nothing for any included router.
    """
    return set(app.openapi()["paths"])


class TestRoutes:
    async def test_app_boots_with_module(self, build_test_app):
        """Module registers cleanly into a minimal FastAPI host."""
        paths = _registered_paths(build_test_app(PagebuilderModule))
        assert any(p.startswith("/api/pagebuilder") for p in paths)
        assert any(p.startswith("/pagebuilder") for p in paths)

    async def test_phase2_endpoints_registered(self, build_test_app):
        """The new revisions + uploads endpoints are wired up."""
        paths = _registered_paths(build_test_app(PagebuilderModule))
        assert "/api/pagebuilder/pages/{page_id}/revisions" in paths
        assert "/api/pagebuilder/pages/{page_id}/revisions/{revision_id}/restore" in paths
        assert "/api/pagebuilder/uploads" in paths
        assert "/api/pagebuilder/uploads/{asset_id}" in paths
        assert "/pagebuilder/media" in paths


class TestMenu:
    def _sidebar(self, *, roles: list[str]) -> list[dict]:
        registry = MenuRegistry()
        PagebuilderModule().register_menu_items(registry)
        items = registry.get_for_user(is_authenticated=True, roles=roles)
        return items[MenuSection.SIDEBAR.value]

    def test_contributes_the_admin_surface(self):
        labels = [i["label"] for i in self._sidebar(roles=["admin"])]
        assert labels == ["Pages", "Site layout", "Media library"]

    def test_items_point_at_real_view_routes(self, build_test_app):
        """A menu entry whose URL 404s is worse than no entry at all."""
        paths = _registered_paths(build_test_app(PagebuilderModule))
        for item in self._sidebar(roles=["admin"]):
            url = item["url"]
            # "/pagebuilder/" is also served at the bare prefix, which is how
            # the schema records it — accept either form.
            assert url in paths or url.rstrip("/") in paths, f"{url} is not a registered route"

    def test_visible_without_a_pagebuilder_role(self):
        """Menu role filtering is a plain intersection with no admin bypass.

        Gating these on the pagebuilder roles would hide them from an admin,
        and would overstate the gating — the views require auth only.
        """
        assert self._sidebar(roles=[]) != []

    def test_hidden_from_anonymous_visitors(self):
        registry = MenuRegistry()
        PagebuilderModule().register_menu_items(registry)
        items = registry.get_for_user(is_authenticated=False, roles=[])
        assert items[MenuSection.SIDEBAR.value] == []

    def test_icons_resolve_in_the_shared_ui(self):
        """Icon names must exist in @simple-module-py/ui's ICON_MAP.

        An unknown name renders as a blank spacer, so a typo is invisible
        rather than loud.
        """
        known = {"file-text", "layout", "image"}
        assert {i["icon"] for i in self._sidebar(roles=["admin"])} <= known
