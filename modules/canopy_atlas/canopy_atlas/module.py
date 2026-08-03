"""CanopyAtlas — the Global Canopy Atlas site.

This module is the GCA *brand*: its design pack, its photography and brand
marks, and the seed that publishes its pages. The widgets those pages are built
from stay in ``pagebuilder``, where they are a generic section library — the
GCA-ness of them lives entirely in the tokens this pack overrides.
"""

from __future__ import annotations

import importlib.metadata
import importlib.resources
from pathlib import Path

from simple_module_core import ModuleBase, ModuleMeta
from simple_module_core.design_packs import DesignPack, DesignPackRegistry
from simple_module_core.public_routes import PublicRouteRegistry

_VERSION = importlib.metadata.version("simple_module_canopy_atlas")

STATIC_MOUNT = "/canopy-atlas/static"
"""URL prefix the brand assets are served from. The seed rewrites content paths
to this, so changing it means re-seeding every page."""

DESIGN_PACK = DesignPack(value="gca", label="Canopy Atlas")

# Modules this one depends on, kept as a constant so depends_on carries no bare
# string literal — see scripts/check_hardcoded_strings.py.
_MODULE_PAGEBUILDER = "PageBuilder"


def _static_dir() -> Path:
    return Path(str(importlib.resources.files("canopy_atlas") / "static"))


class CanopyAtlasModule(ModuleBase):
    meta = ModuleMeta(
        name="CanopyAtlas",
        route_prefix="/api/canopy-atlas",
        view_prefix="/canopy-atlas",
        # The seed writes through pagebuilder's API and the pack styles its
        # widgets, so the host must boot them in that order.
        depends_on=[_MODULE_PAGEBUILDER],
        version=_VERSION,
        # The framework API version (1.0.0) is decoupled from the framework
        # package version (0.0.x) — this range is correct as written.
        requires_framework=">=1.0,<2.0",
    )

    def register_design_packs(self, registry: DesignPackRegistry) -> None:
        registry.register(DESIGN_PACK)

    def static_mounts(self) -> dict[str, Path]:
        return {STATIC_MOUNT: _static_dir()}

    def register_public_routes(self, registry: PublicRouteRegistry) -> None:
        """Let anonymous visitors load the brand assets.

        A static mount is not public just because it is static —
        ``AuthMiddleware`` gates every request, so without this every logo and
        photograph on the public site 302s to the login page.

        The trailing slash matters: prefix rules match with ``str.startswith``,
        so ``/canopy-atlas/static`` alone would also exempt any sibling path
        that merely begins with those characters.
        """
        registry.add_prefix(f"{STATIC_MOUNT}/")
