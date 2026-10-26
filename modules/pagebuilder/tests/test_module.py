"""Smoke tests for the PageBuilder module."""

from __future__ import annotations

import importlib.metadata

import pytest
from fastapi.routing import iter_route_contexts
from pagebuilder.module import PagebuilderModule
from pagebuilder.permissions import PERM_APPROVE, PERM_EDIT, PERM_PUBLISH
from simple_module_core.menu import MenuRegistry, MenuSection
from starlette.requests import Request


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


def _route_paths(app) -> set[str]:
    """Every path the app serves, view routes included.

    Not ``app.routes``: since FastAPI 0.141 ``include_router`` wraps the
    sub-router in one lazily-resolved ``_IncludedRouter`` with no ``path``.
    Not the OpenAPI schema: since framework 0.0.37 view routers are included
    with ``include_in_schema=False``, so the schema lists only ``/api/...``
    (#186).
    ``iter_route_contexts`` ships with the FastAPI 0.141 every lock here
    resolves, so it is imported unguarded.
    """
    return {r.path for r in iter_route_contexts(app.routes) if r.path}


class TestRoutes:
    async def test_app_boots_with_module(self, build_test_app):
        """Module registers cleanly into a minimal FastAPI host."""
        paths = _route_paths(build_test_app(PagebuilderModule))
        assert any(p.startswith("/api/pagebuilder") for p in paths)
        assert any(p.startswith("/pagebuilder") for p in paths)

    async def test_phase2_endpoints_registered(self, build_test_app):
        """The new revisions + uploads endpoints are wired up."""
        paths = _route_paths(build_test_app(PagebuilderModule))
        assert "/api/pagebuilder/pages/{page_id}/revisions" in paths
        assert "/api/pagebuilder/pages/{page_id}/revisions/{revision_id}/restore" in paths
        assert "/api/pagebuilder/uploads" in paths
        assert "/api/pagebuilder/uploads/{asset_id}" in paths
        assert "/pagebuilder/media" in paths


def _request(*, user: object | None, held: set[str]) -> Request:
    """A request as the layout middleware leaves it: principal and permissions resolved."""
    return Request({"type": "http", "state": {"user": user, "resolved_permissions": held}})


class TestMenu:
    async def _sidebar(self, *, roles: list[str], held: set[str] | None = None) -> list[dict]:
        registry = MenuRegistry()
        PagebuilderModule().register_menu_items(registry)
        held = {"*"} if held is None else held
        items = await registry.get_for_request(
            _request(user=object(), held=held), is_authenticated=True, roles=roles
        )
        return items[MenuSection.SIDEBAR.value]

    async def test_contributes_the_admin_surface(self):
        labels = [i["label"] for i in await self._sidebar(roles=["admin"])]
        assert labels == ["Pages", "Site layout", "Media library", "Import / Export"]

    async def test_items_point_at_real_view_routes(self, build_test_app):
        """A menu entry whose URL 404s is worse than no entry at all."""
        paths = _route_paths(build_test_app(PagebuilderModule))
        for item in await self._sidebar(roles=["admin"]):
            url = item["url"]
            # "/pagebuilder/" is also served at the bare prefix, which is the
            # form the route table records — accept either.
            assert url in paths or url.rstrip("/") in paths, f"{url} is not a registered route"

    async def test_visible_without_a_pagebuilder_role(self):
        """Menu role filtering is a plain intersection with no admin bypass.

        Gating these on the pagebuilder roles would hide them from an admin,
        and would overstate the gating — the views require auth only.
        """
        labels = [i["label"] for i in await self._sidebar(roles=[], held=set())]
        assert labels == ["Pages", "Site layout", "Media library"]

    @pytest.mark.parametrize(
        ("held", "shown"),
        [
            (set(), False),
            ({PERM_EDIT}, False),
            ({PERM_PUBLISH}, True),
            ({PERM_APPROVE}, True),
        ],
    )
    async def test_import_export_needs_publish_or_approve(self, held, shown):
        """The menu asks what ``/pagebuilder/content`` asks, so it never offers a 403."""
        labels = [i["label"] for i in await self._sidebar(roles=[], held=held)]
        assert ("Import / Export" in labels) is shown

    async def test_hidden_from_anonymous_visitors(self):
        registry = MenuRegistry()
        PagebuilderModule().register_menu_items(registry)
        items = await registry.get_for_request(
            _request(user=None, held=set()), is_authenticated=False, roles=[]
        )
        assert items[MenuSection.SIDEBAR.value] == []

    async def test_icons_resolve_in_the_shared_ui(self):
        """Icon names must exist in @simple-module-py/ui's ICON_MAP.

        An unknown name renders as a blank spacer, so a typo is invisible
        rather than loud.
        """
        known = {"file-text", "layout", "image", "package"}
        assert {i["icon"] for i in await self._sidebar(roles=["admin"])} <= known
