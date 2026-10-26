"""Page revisions, restore markers and revision diffs.

Split from ``_pages`` (300-line cap, #133) when restore markers gained the
contributed sections a restore also wrote (#80).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from pagebuilder.contracts.schemas._pages import PuckData
from pagebuilder.models import RevisionEvent


class PageRevisionRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    page_id: int
    title: str
    meta_description: str | None
    og_image: str | None
    event: RevisionEvent
    note: str | None
    created_at: datetime
    created_by: str | None


class PageRevisionDetail(PageRevisionRead):
    data: PuckData


class RestoredSection(BaseModel):
    """One contributed section a restore also wrote: how many of its rows.

    A count only — never which rows — so it is safe beside any page's history,
    whoever reads it. ``label_key`` is the contributor's catalogue key.
    """

    section: str
    label_key: str | None = None
    count: int


class PageRestoreMarker(BaseModel):
    """A bulk snapshot restore that wrote this page.

    Not a revision — there is no page state behind it to compare or restore —
    so a list of its own beside ``items``, derived on read from the approved
    import. The client interleaves the two by time.
    """

    import_id: int
    snapshot_id: int
    change: Literal["created", "overwritten"]
    restored_at: datetime
    restored_by: str | None
    sections: list[RestoredSection] = Field(default_factory=list)
    """What the same restore wrote in each contributed section (#80)."""


class PageRevisionListResponse(BaseModel):
    items: list[PageRevisionRead]
    restores: list[PageRestoreMarker] = Field(default_factory=list)


class BlockChange(BaseModel):
    id: str
    type: str | None = None
    fields: list[str] = Field(default_factory=list)
    type_before: str | None = None


class MetadataChange(BaseModel):
    before: Any = None
    after: Any = None


class RevisionDiffResponse(BaseModel):
    """Block-level diff between two revisions.

    ``metadata`` only contains keys whose value actually changed;
    ``blocks`` is always present so the client can render an empty diff
    ("no changes") deterministically.
    """

    before_id: int
    after_id: int
    metadata: dict[str, MetadataChange] = Field(default_factory=dict)
    blocks: dict[str, list[BlockChange]] = Field(default_factory=dict)
