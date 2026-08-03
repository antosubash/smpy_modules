"""Module-scoped state container.

Stored as ``app.state.pagebuilder`` by
:meth:`PagebuilderModule.register_settings`. Set once during boot,
treat as read-only after.
"""

from __future__ import annotations

from dataclasses import dataclass

from pagebuilder.settings import PagebuilderSettings


@dataclass
class PagebuilderServices:
    """PageBuilder module singletons."""

    settings: PagebuilderSettings
