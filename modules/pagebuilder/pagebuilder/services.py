"""Module-scoped state container.

Stored as ``app.state.pagebuilder`` by
:meth:`PagebuilderModule.register_settings`. Set once during boot,
treat as read-only after.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from pagebuilder.settings import PagebuilderSettings
from pagebuilder.snapshots.registry import SectionRegistry


@dataclass
class PagebuilderServices:
    """PageBuilder module singletons."""

    settings: PagebuilderSettings
    bundle_sections: SectionRegistry = field(default_factory=SectionRegistry)
    """Sections other modules contribute to the content bundle (#80), added
    through ``pagebuilder.contracts.bundle.register_section`` from their
    ``on_startup``. Created here, during app construction, so it exists before
    any module starts."""
