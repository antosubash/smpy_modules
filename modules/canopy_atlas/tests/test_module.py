"""Smoke tests for the CanopyAtlas module.

The module's whole backend surface is its static mount and its design pack. A
static mount is *not* public by default: AuthMiddleware gates every request, so
without a PublicRouteRegistry entry every logo and photograph 302s to the login
page and the public site renders as broken images.

The ``build_test_app`` and ``fake_event_bus`` fixtures come from the
``simple_module_test`` pytest plugin (registered via entry_points when
that package is installed). No conftest.py is required.
"""

from __future__ import annotations

from canopy_atlas.module import CanopyAtlasModule
from simple_module_core.design_packs import DesignPackRegistry
from simple_module_core.public_routes import PublicRouteRegistry


class TestMeta:
    def test_meta_name(self):
        assert CanopyAtlasModule.meta.name == "CanopyAtlas"

    def test_meta_requires_framework(self):
        assert CanopyAtlasModule.meta.requires_framework is not None

    def test_depends_on_pagebuilder(self):
        # The seed writes through pagebuilder's API and the design pack styles
        # its widgets, so the host must boot them in that order.
        assert "PageBuilder" in CanopyAtlasModule.meta.depends_on


class TestDesignPack:
    def test_registers_the_gca_pack(self):
        registry = DesignPackRegistry()
        CanopyAtlasModule().register_design_packs(registry)
        assert [(p.value, p.label) for p in registry.all()] == [("gca", "Canopy Atlas")]


class TestStaticAssets:
    def test_mount_points_at_a_real_directory(self):
        mounts = CanopyAtlasModule().static_mounts()
        assert "/canopy-atlas/static" in mounts
        assert mounts["/canopy-atlas/static"].is_dir()

    def test_mount_is_exempt_from_auth(self):
        registry = PublicRouteRegistry()
        CanopyAtlasModule().register_public_routes(registry)
        assert "/canopy-atlas/static/" in [route.pattern for route in registry.routes]

    def test_public_prefix_does_not_leak_to_siblings(self):
        # Prefix rules match with str.startswith, so an unterminated prefix
        # also exempts any sibling path that merely begins with it. That
        # shipped as a real bug once, with "/p" matching "/pagebuilder/".
        registry = PublicRouteRegistry()
        CanopyAtlasModule().register_public_routes(registry)
        assert all(route.pattern.endswith("/") for route in registry.routes)
