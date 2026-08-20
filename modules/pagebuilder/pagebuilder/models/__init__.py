"""SQLModel tables for the pagebuilder module.

A package rather than one file: Alembic's ``build_module_metadata`` imports
``<pkg>.models`` and nothing else, so every table has to be reachable from this
name — while each file stays inside the repo's 300-line cap. Import from
``pagebuilder.models`` exactly as before; the split is not part of the contract.
"""

from __future__ import annotations

from pagebuilder.models._base import PAGE_TABLE, Base
from pagebuilder.models._layout import Layout, LayoutRevision
from pagebuilder.models._media import MediaAsset
from pagebuilder.models._page import (
    NOT_TRASHED,
    Page,
    PageRevision,
    PageStatus,
    RevisionEvent,
)
from pagebuilder.models._redirect import PageRedirect

__all__ = [
    "NOT_TRASHED",
    "PAGE_TABLE",
    "Base",
    "Layout",
    "LayoutRevision",
    "MediaAsset",
    "Page",
    "PageRedirect",
    "PageRevision",
    "PageStatus",
    "RevisionEvent",
]
