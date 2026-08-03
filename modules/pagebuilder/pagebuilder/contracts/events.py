"""Domain events other modules can subscribe to."""

from __future__ import annotations

from dataclasses import dataclass

from simple_module_core.events import Event


@dataclass
class PageDeleted(Event):
    """A page and its revisions were removed.

    Modules that key their own rows to a page must handle this. Nothing else
    can: the framework gives each module its own ``MetaData``, so a
    cross-module foreign key cannot be declared and there is no
    ``ON DELETE CASCADE`` to fall back on.

    It matters more than "a row points at nothing" suggests — SQLite reuses a
    deleted row's id, so a stale reference does not stay dangling, it silently
    re-attaches to whatever page is created next.
    """

    page_id: int
    slug: str
