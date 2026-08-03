"""Smoke tests for the PageBuilder module."""

from __future__ import annotations

from pagebuilder.module import PagebuilderModule


class TestMeta:
    def test_meta_name(self):
        assert PagebuilderModule.meta.name == "PageBuilder"

    def test_meta_requires_framework(self):
        assert PagebuilderModule.meta.requires_framework is not None

    def test_meta_version_bumped(self):
        assert PagebuilderModule.meta.version == "0.2.0"


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
